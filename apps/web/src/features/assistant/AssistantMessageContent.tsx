import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

import { SourceCard } from '../../components/SourceCard'
import type { AssistantSource } from '../../types'

/* 重点句标记（§7 用户反馈）：模型把重点句/结论句包在 ==…== 里，渲染成红色强调。
   手写 mdast 遍历：只拆分纯文本节点里的 ==对==，代码块/公式天然不受影响。 */
type MdastNode = { type: string; value?: string; children?: MdastNode[] }

function splitKeyPointSegments(value: string): Array<{ text: string; key: boolean }> {
  const segments: Array<{ text: string; key: boolean }> = []
  const pattern = /==([^=\n]+)==/g
  let cursor = 0
  for (let match = pattern.exec(value); match !== null; match = pattern.exec(value)) {
    if (match.index > cursor) segments.push({ text: value.slice(cursor, match.index), key: false })
    segments.push({ text: match[1], key: true })
    cursor = match.index + match[0].length
  }
  if (cursor < value.length) segments.push({ text: value.slice(cursor), key: false })
  return segments
}

export function remarkKeyPoint() {
  return (tree: MdastNode) => {
    const walk = (node: MdastNode) => {
      const children = node.children
      if (!Array.isArray(children)) return
      for (let index = 0; index < children.length; index += 1) {
        const child = children[index]
        if (child.type === 'text' && child.value && child.value.includes('==')) {
          const segments = splitKeyPointSegments(child.value)
          if (segments.length === 1 && !segments[0].key) continue
          const replacement = segments.map((segment) => (
            segment.key
              ? {
                  type: 'emphasis',
                  data: { hName: 'span', hProperties: { className: ['assistant-key-point'] } },
                  children: [{ type: 'text', value: segment.text }],
                }
              : { type: 'text', value: segment.text }
          ))
          children.splice(index, 1, ...replacement)
          index += replacement.length - 1
          continue
        }
        walk(child)
      }
    }
    walk(tree)
  }
}

export function AssistantMessageMarkdown({ content }: { content: string }) {
  return <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm, remarkKeyPoint]} rehypePlugins={[rehypeKatex]}>{content}</ReactMarkdown>
}

export function AssistantMessageSource({ source, onOpen }: {
  source: AssistantSource
  onOpen?: () => void
}) {
  if (source.source_type === 'web' && source.url) {
    return (
      <a className="source-card web-source-card" href={source.url} target="_blank" rel="noreferrer">
        <span className="source-card-icon" aria-hidden="true">↗</span>
        <span className="source-card-body">
          <span className="source-card-meta">
            网络补充 · {source.site_name}
            {source.published_at ? ` · 发布于 ${source.published_at}` : ''}
            {source.retrieved_at ? ` · 检索于 ${new Date(source.retrieved_at).toLocaleDateString('zh-CN')}` : ''}
          </span>
          <strong>{source.title}</strong>
          <small>{source.snippet}</small>
        </span>
      </a>
    )
  }
  if (!source.material_id || !source.page_number) return null
  return (
    <SourceCard
      title={source.lecture_title ?? '课程资料'}
      pageNumber={source.page_number}
      locationLabel={source.location_label}
      quote={source.snippet}
      onOpen={onOpen}
    />
  )
}
