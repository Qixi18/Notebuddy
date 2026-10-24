import type { DocMark, DocNode, NotebookDocumentBlock, NotebookDocumentResponse, OutlineItem } from '../../types'

export type { DocMark, DocNode, NotebookDocumentResponse, OutlineItem }

export type CalloutTone = 'tip' | 'warning' | 'note'

const INLINE_PATTERN = /(\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|`[^`\n]+`|\$[^$\n]+\$|\[[^\]\n]+\]\([^)\s]+\)|\*[^*\n]+\*|_[^_\n]+_)/g

export function newBlockId(prefix = 'block'): string {
  const random = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
    : Math.random().toString(36).slice(2, 14)
  return `${prefix}-${random}`
}

export function emptyDocument(): DocNode {
  return { type: 'doc', content: [] }
}

export function normalizeDocument(content: DocNode | null | undefined): DocNode {
  if (!content || content.type !== 'doc') return emptyDocument()
  const used = new Set<string>()
  const walk = (node: DocNode, topLevel: boolean): DocNode => {
    const copy: DocNode = { ...node }
    if (Array.isArray(node.content)) copy.content = node.content.map((child) => walk(child, false))
    if (topLevel && !['horizontalRule', 'text', 'image', 'blockMath'].includes(node.type)) {
      const attrs = { ...(node.attrs ?? {}) }
      if (typeof attrs.blockId !== 'string' || !attrs.blockId || used.has(attrs.blockId)) {
        attrs.blockId = newBlockId(node.type)
      }
      used.add(attrs.blockId as string)
      copy.attrs = attrs
    }
    return copy
  }
  return { ...content, content: (content.content ?? []).map((child) => walk(child, true)) }
}

export function extractOutline(doc: DocNode): OutlineItem[] {
  const items: OutlineItem[] = []
  for (const node of doc.content ?? []) {
    if (node.type !== 'heading') continue
    const text = plainText(node).trim()
    if (!text) continue
    const level = Number(node.attrs?.level ?? 1)
    const id = typeof node.attrs?.blockId === 'string' ? node.attrs.blockId : ''
    if (!id) continue
    items.push({ id, level: level >= 1 && level <= 3 ? level : 2, text })
  }
  return items
}

export function plainText(node: DocNode | null | undefined): string {
  if (!node) return ''
  if (node.type === 'text') return node.text ?? ''
  if (node.type === 'hardBreak') return '\n'
  if (node.type === 'inlineMath') return `$${String(node.attrs?.latex ?? '')}$`
  if (node.type === 'blockMath') return `$$${String(node.attrs?.latex ?? '')}$$`
  if (node.type === 'image') return String(node.attrs?.alt ?? '')
  const separator = ['doc', 'bulletList', 'orderedList', 'taskList', 'table'].includes(node.type) ? '\n' : ''
  return (node.content ?? []).map(plainText).filter(Boolean).join(separator)
}

export function countText(doc: DocNode): number {
  return plainText(doc).replace(/\s/g, '').length
}

export function excerptAroundSelection(doc: DocNode, selection?: string, limit = 2000): string {
  const text = plainText(doc)
  const selected = selection?.trim()
  const position = selected ? text.indexOf(selected) : -1
  const start = position < 0 ? 0 : Math.max(0, position - Math.floor(limit / 3))
  return text.slice(start, start + limit)
}

/** Stable serialisation for dirty checks: key order must not create false positives. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(',')}]`
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

export function markdownToNodes(text: string): DocNode[] {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const nodes: DocNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) { index += 1; continue }

    const fence = /^\s*```\s*([A-Za-z0-9_+-]*)\s*$/.exec(line)
    if (fence) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) { body.push(lines[index]); index += 1 }
      index += 1
      nodes.push({ type: 'codeBlock', attrs: fence[1] ? { language: fence[1] } : {}, content: body.length ? [{ type: 'text', text: body.join('\n') }] : [] })
      continue
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      nodes.push({ type: 'heading', attrs: { level: heading[1].length }, content: inlineNodes(heading[2].trim()) })
      index += 1
      continue
    }

    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) { nodes.push({ type: 'horizontalRule' }); index += 1; continue }

    const task = /^\s*[-*+]\s+\[([ xX])\]\s+(.*)$/.exec(line)
    if (task) {
      const items: DocNode[] = []
      while (index < lines.length) {
        const match = /^\s*[-*+]\s+\[([ xX])\]\s+(.*)$/.exec(lines[index])
        if (!match) break
        items.push({ type: 'taskItem', attrs: { checked: match[1].toLowerCase() === 'x' }, content: [{ type: 'paragraph', content: inlineNodes(match[2].trim()) }] })
        index += 1
      }
      nodes.push({ type: 'taskList', attrs: { blockId: newBlockId('task') }, content: items })
      continue
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line)
    if (bullet) {
      const items: DocNode[] = []
      while (index < lines.length) {
        const match = /^\s*[-*+]\s+(.*)$/.exec(lines[index])
        if (!match || /^\s*[-*+]\s+\[[ xX]\]/.test(lines[index])) break
        items.push({ type: 'listItem', content: [{ type: 'paragraph', content: inlineNodes(match[1].trim()) }] })
        index += 1
      }
      nodes.push({ type: 'bulletList', attrs: { blockId: newBlockId('list') }, content: items })
      continue
    }

    const ordered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line)
    if (ordered) {
      const items: DocNode[] = []
      while (index < lines.length) {
        const match = /^\s*(\d+)[.)]\s+(.*)$/.exec(lines[index])
        if (!match) break
        items.push({ type: 'listItem', content: [{ type: 'paragraph', content: inlineNodes(match[2].trim()) }] })
        index += 1
      }
      nodes.push({ type: 'orderedList', attrs: { blockId: newBlockId('olist'), start: Number(ordered[1]) || 1 }, content: items })
      continue
    }

    const quote = /^\s*>\s?(.*)$/
    if (quote.test(line)) {
      const quoted: string[] = []
      while (index < lines.length && quote.test(lines[index])) {
        quoted.push((quote.exec(lines[index]) as RegExpExecArray)[1])
        index += 1
      }
      nodes.push({ type: 'blockquote', attrs: { blockId: newBlockId('quote') }, content: [paragraph(quoted)] })
      continue
    }

    if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])) {
      const rows = [line]
      index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) { rows.push(lines[index]); index += 1 }
      nodes.push(tableFromRows(rows))
      continue
    }

    const paragraphLines: string[] = []
    while (index < lines.length && lines[index].trim() && !startsBlock(lines, index)) {
      paragraphLines.push(lines[index].trim())
      index += 1
    }
    if (!paragraphLines.length) { paragraphLines.push(line.trim()); index += 1 }
    nodes.push(paragraph(paragraphLines))
  }

  return nodes.map((node) => {
    if (node.type !== 'paragraph' && node.type !== 'heading') return node
    if (node.attrs?.blockId) return node
    return { ...node, attrs: { ...(node.attrs ?? {}), blockId: newBlockId(node.type) } }
  })
}

function startsBlock(lines: string[], index: number): boolean {
  const line = lines[index]
  if (/^\s*```/.test(line) || /^(#{1,3})\s+/.test(line) || /^\s*[-*+]\s+/.test(line)) return true
  if (/^\s*\d+[.)]\s+/.test(line) || /^\s*>\s?/.test(line)) return true
  if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) return true
  return line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])
}

function paragraph(lines: string[]): DocNode {
  const content: DocNode[] = []
  lines.forEach((line, position) => {
    if (position) content.push({ type: 'hardBreak' })
    content.push(...inlineNodes(line))
  })
  return { type: 'paragraph', attrs: { blockId: newBlockId('p') }, content }
}

function tableFromRows(rows: string[]): DocNode {
  const cells = rows.map((row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim()))
  const width = Math.max(...cells.map((row) => row.length))
  return {
    type: 'table',
    attrs: { blockId: newBlockId('table') },
    content: cells.map((row, index) => ({
      type: 'tableRow',
      content: row.concat(Array(Math.max(0, width - row.length)).fill('')).map((value) => ({
        type: index === 0 ? 'tableHeader' : 'tableCell',
        content: [{ type: 'paragraph', content: inlineNodes(value) }],
      })),
    })),
  }
}

function inlineNodes(text: string): DocNode[] {
  const nodes: DocNode[] = []
  let cursor = 0
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const start = match.index ?? 0
    if (start > cursor) nodes.push({ type: 'text', text: text.slice(cursor, start) })
    nodes.push(...inlineToken(match[0]))
    cursor = start + match[0].length
  }
  if (cursor < text.length) nodes.push({ type: 'text', text: text.slice(cursor) })
  return mergeText(nodes)
}

function inlineToken(token: string): DocNode[] {
  if (/^\*\*[^*]+\*\*$/.test(token)) return marked(token.slice(2, -2), { type: 'bold' })
  if (/^__[^_]+__$/.test(token)) return marked(token.slice(2, -2), { type: 'bold' })
  if (/^~~[^~]+~~$/.test(token)) return marked(token.slice(2, -2), { type: 'strike' })
  if (/^`[^`]+`$/.test(token)) return marked(token.slice(1, -1), { type: 'code' })
  if (/^\$[^$]+\$$/.test(token)) return [{ type: 'inlineMath', attrs: { latex: token.slice(1, -1).trim() } }]
  const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token)
  if (link && /^(https?:\/\/|mailto:)/i.test(link[2])) return marked(link[1], { type: 'link', attrs: { href: link[2] } })
  if (/^\*[^*]+\*$/.test(token) || /^_[^_]+_$/.test(token)) return marked(token.slice(1, -1), { type: 'italic' })
  return [{ type: 'text', text: token }]
}

function marked(text: string, mark: DocMark): DocNode[] {
  if (!text) return []
  return [{ type: 'text', text, marks: [mark] }]
}

function mergeText(nodes: DocNode[]): DocNode[] {
  const merged: DocNode[] = []
  for (const node of nodes) {
    if (node.type === 'text' && !node.text) continue
    const previous = merged[merged.length - 1]
    if (previous?.type === 'text' && node.type === 'text' && JSON.stringify(previous.marks) === JSON.stringify(node.marks)) {
      previous.text = `${previous.text ?? ''}${node.text ?? ''}`
    } else {
      merged.push({ ...node })
    }
  }
  return merged
}

export function docToMarkdown(doc: DocNode): string {
  return (doc.content ?? []).map((node) => nodeMarkdown(node, 0)).filter(Boolean).join('\n\n').trim() + '\n'
}

function nodeMarkdown(node: DocNode, depth: number): string {
  const pad = '  '.repeat(depth)
  const attrs = node.attrs ?? {}
  switch (node.type) {
    case 'heading':
      return `${'#'.repeat(Math.min(6, Math.max(1, Number(attrs.level ?? 1))))} ${inlineMarkdown(node)}`
    case 'paragraph':
      return `${pad}${inlineMarkdown(node)}`
    case 'bulletList':
      return (node.content ?? []).map((item) => {
        const [first, ...rest] = nodeMarkdown(item, depth + 1).split('\n')
        return [`${pad}- ${first.trim()}`, ...rest].join('\n')
      }).join('\n')
    case 'orderedList':
      return (node.content ?? []).map((item, index) => {
        const [first, ...rest] = nodeMarkdown(item, depth + 1).split('\n')
        return [`${pad}${index + 1}. ${first.trim()}`, ...rest].join('\n')
      }).join('\n')
    case 'taskList':
      return (node.content ?? []).map((item) => {
        const checked = item.attrs?.checked ? 'x' : ' '
        const [first, ...rest] = nodeMarkdown(item, depth + 1).split('\n')
        return [`${pad}- [${checked}] ${first.trim()}`, ...rest].join('\n')
      }).join('\n')
    case 'blockquote':
      return (node.content ?? []).map((child) => nodeMarkdown(child, 0)).join('\n').split('\n').map((line) => `${pad}> ${line}`).join('\n')
    case 'codeBlock':
      return `${pad}\`\`\`${String(attrs.language ?? '')}\n${plainText(node)}\n${pad}\`\`\``
    case 'horizontalRule':
      return `${pad}---`
    case 'table': {
      const rows = (node.content ?? []).map((row) => (row.content ?? []).map((cell) => inlineMarkdown(cell).replace(/\|/g, '\\|')))
      if (!rows.length) return ''
      const divider = rows[0].map(() => '---')
      return [rows[0], divider, ...rows.slice(1)].map((row) => `| ${row.join(' | ')} |`).join('\n')
    }
    case 'callout':
      return [`> **${String(attrs.title ?? '重点提示')}**`, ...(node.content ?? []).flatMap((child) => nodeMarkdown(child, 0).split('\n')).map((line) => `> ${line}`)].join('\n')
    case 'example':
      return [`**${String(attrs.title ?? '例题')}**`, ...(node.content ?? []).map((child) => nodeMarkdown(child, 0))].join('\n')
    case 'blockMath':
      return `$$${String(attrs.latex ?? '')}$$`
    case 'image':
      return `![${String(attrs.alt ?? '')}](${String(attrs.src ?? '')})`
    default:
      return `${pad}${plainText(node)}`
  }
}

function inlineMarkdown(node: DocNode): string {
  return (node.content ?? []).map((child) => {
    if (child.type === 'text') {
      let text = child.text ?? ''
      for (const mark of [...(child.marks ?? [])].reverse()) {
        if (mark.type === 'bold') text = `**${text}**`
        else if (mark.type === 'italic') text = `*${text}*`
        else if (mark.type === 'strike') text = `~~${text}~~`
        else if (mark.type === 'code') text = `\`${text}\``
        else if (mark.type === 'underline') text = `<u>${text}</u>`
        else if (mark.type === 'link') text = `[${text}](${String(mark.attrs?.href ?? '')})`
      }
      return text
    }
    if (child.type === 'hardBreak') return '  \n'
    if (child.type === 'inlineMath') return `$${String(child.attrs?.latex ?? '')}$`
    if (child.type === 'image') return `![${String(child.attrs?.alt ?? '')}](${String(child.attrs?.src ?? '')})`
    return plainText(child)
  }).join('')
}

export function docToPlainBlocks(doc: DocNode): Array<{ id: string; type: 'h1' | 'h2' | 'p' | 'bullet'; text: string }> {
  const blocks: Array<{ id: string; type: 'h1' | 'h2' | 'p' | 'bullet'; text: string }> = []
  for (const node of doc.content ?? []) {
    const id = typeof node.attrs?.blockId === 'string' ? node.attrs.blockId : newBlockId()
    if (node.type === 'heading') {
      blocks.push({ id, type: Number(node.attrs?.level ?? 1) === 1 ? 'h1' : 'h2', text: plainText(node) })
    } else if (node.type === 'paragraph') {
      blocks.push({ id, type: 'p', text: plainText(node) })
    } else if (node.type === 'bulletList') {
      (node.content ?? []).forEach((item, index) => blocks.push({ id: `${id}-${index + 1}`, type: 'bullet', text: plainText(item) }))
    } else {
      blocks.push({ id, type: 'p', text: plainText(node) })
    }
  }
  return blocks
}

export function legacyBlocksToDocument(blocks: NotebookDocumentBlock[]): DocNode {
  const content: DocNode[] = []
  for (const block of blocks) {
    if (block.type === 'h1' || block.type === 'h2') {
      content.push({
        type: 'heading',
        attrs: { level: block.type === 'h1' ? 1 : 2, blockId: block.id },
        content: block.text.trim() ? [{ type: 'text', text: block.text }] : [],
      })
      continue
    }
    if (block.type === 'bullet') {
      content.push({
        type: 'bulletList',
        attrs: { blockId: block.id },
        content: block.text.split('\n').filter((line) => line.trim()).map((line) => ({
          type: 'listItem',
          content: [{ type: 'paragraph', content: [{ type: 'text', text: line.trim() }] }],
        })),
      })
      continue
    }
    const nodes = markdownToNodes(block.text)
    nodes.forEach((node, index) => {
      const attrs = { ...(node.attrs ?? {}) }
      attrs.blockId = index === 0 ? block.id : newBlockId(node.type)
      content.push({ ...node, attrs })
    })
  }
  return { type: 'doc', content }
}
