import type { AssistantSource } from '../../types'

/**
 * 把后端提示词要求模型输出的来源标记解析成角标。
 *
 * 标记规范与 apps/backend/app/ai/evidence.py 中的正则保持一致：
 * - 课程资料：`[课程资料：讲次 | 第 N 页]`，按 lecture_title + page_number 精确匹配 sources；
 *   页码支持枚举与区间（`第 2、3、5 页` / `第 2,3 页` / `第 2-5 页`），一个标记可命中多个来源；
 * - 网络来源：`[网络来源 N]`，N 是检索结果序号（后端按 N-1 索引），优先按索引匹配，
 *   越界或重复时退回「下一个未用过的网络来源」，仍找不到就不编号；
 * - `[通用解释]` / `[模型推断]`：不属于任何来源，摘成段落级标记徽标。
 *
 * 匹配不到的标记一律降级为纯文本（只删除），宁可少标不能标错。
 * 角标编号 = 该来源首次被引用的顺序（1 起），与卡底依据行 chips 的编号一一对应；
 * 同一个来源在多处被引用时复用同一个编号。
 */

export type CiteRef = {
  /** 角标编号，等于该来源首次被引用的顺序（1 起） */
  no: number
  kind: 'course' | 'notebook' | 'web'
  sourceIndex: number
  title: string
  page?: number
}

export type ParagraphCitations = {
  text: string
  refs: CiteRef[]
  /** 段落里出现的非来源标记：「通用解释」「模型推断」 */
  flags: string[]
}

export type ParsedCitations = { paragraphs: ParagraphCitations[] }

const COURSE_MARKER = /\[课程资料：([^\]|]+?)\s*\|\s*第\s*([\d、,，\s\-–—~至到]+?)\s*页[^\]]*\]/g
const WEB_MARKER = /\[网络来源\s+(\d+)[^\]]*\]/g
const FLAG_LABELS: ReadonlyArray<{ pattern: RegExp; label: string }> = [
  { pattern: /\[通用解释\]/g, label: '通用解释' },
  { pattern: /\[模型推断\]/g, label: '模型推断' },
]

/** 单个标记最多展开的页码数，防止「第 1-9999 页」这类异常数据炸开 */
const MAX_PAGES_PER_MARKER = 50

/** 把「第 N 页」的 N 部分解析成页码列表：支持 2、3、5 / 2,3,5 / 2-5 / 2 到 5。 */
function parsePageNumbers(raw: string): number[] {
  const normalized = raw.replace(/[至到—–]/g, '-')
  const pages: number[] = []
  for (const token of normalized.split(/[^\d-]+/)) {
    if (!token) continue
    const parts = token.split('-').filter(Boolean).map(Number).filter((page) => page > 0)
    if (parts.length >= 2 && parts[0] < parts[1]) {
      const last = Math.min(parts[1], parts[0] + MAX_PAGES_PER_MARKER - 1)
      for (let page = parts[0]; page <= last; page += 1) pages.push(page)
    } else {
      pages.push(...parts)
    }
  }
  return [...new Set(pages)].sort((a, b) => a - b)
}

function cleanText(text: string): string {
  return text.replace(/[ \t]{2,}/g, ' ').replace(/[ \t]+\n/g, '\n').trim()
}

export function parseCitations(content: string, sources: readonly AssistantSource[]): ParsedCitations {
  const webPositions = sources
    .map((source, index) => ({ source, index }))
    .filter((item) => item.source.source_type === 'web')

  const paragraphs = content
    .split(/\n{2,}/)
    .map((chunk): ParagraphCitations => ({ text: chunk, refs: [], flags: [] }))

  /* 按「来源首次被引用」的顺序编号：sourceIndex 映射到 1、2、3… */
  const assignedNumbers = new Map<number, number>()
  let nextNo = 1
  function numberOf(sourceIndex: number): number {
    const existing = assignedNumbers.get(sourceIndex)
    if (existing !== undefined) return existing
    const no = nextNo
    nextNo += 1
    assignedNumbers.set(sourceIndex, no)
    return no
  }

  for (const paragraph of paragraphs) {
    let text = paragraph.text

    for (const { pattern, label } of FLAG_LABELS) {
      if (pattern.test(text)) {
        paragraph.flags.push(label)
        text = text.replace(pattern, '')
      }
      pattern.lastIndex = 0
    }

    /* 一个标记可以列多页（第 2、3、5 页），每命中一个来源生成一个角标 */
    text = text.replace(COURSE_MARKER, (_match, rawTitle: string, rawPages: string) => {
      const title = rawTitle.trim()
      const matched: number[] = []
      for (const page of parsePageNumbers(rawPages)) {
        const index = sources.findIndex((source, candidate) =>
          source.source_type !== 'web'
          && !matched.includes(candidate)
          && (source.lecture_title ?? '').trim() === title
          && source.page_number === page,
        )
        if (index >= 0) matched.push(index)
      }
      if (matched.length === 0) return ''
      for (const index of matched) {
        paragraph.refs.push({
          no: numberOf(index),
          kind: 'course',
          sourceIndex: index,
          title: sources[index].lecture_title ?? title,
          page: sources[index].page_number ?? undefined,
        })
      }
      return ''
    })

    const usedWeb = new Set<number>()
    text = text.replace(WEB_MARKER, (_match, rawNo: string) => {
      const wanted = Number(rawNo) - 1
      let position = wanted >= 0 && wanted < webPositions.length ? wanted : -1
      if (position < 0 || usedWeb.has(position)) {
        position = webPositions.findIndex((_item, candidate) => !usedWeb.has(candidate))
      }
      if (position < 0) return ''
      usedWeb.add(position)
      const { index } = webPositions[position]
      const source = sources[index]
      paragraph.refs.push({ no: numberOf(index), kind: 'web', sourceIndex: index, title: source.title ?? '网络来源' })
      return ''
    })

    paragraph.text = cleanText(text)
    const seen = new Set<number>()
    paragraph.refs = paragraph.refs.filter((ref) => !seen.has(ref.no) && seen.add(ref.no))
  }

  return { paragraphs: paragraphs.filter((paragraph) => paragraph.text.length > 0) }
}
