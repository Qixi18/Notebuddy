import { NodeViewContent, NodeViewWrapper, type NodeViewProps } from '@tiptap/react'

const TONES = [
  { value: 'tip', label: '重点' },
  { value: 'note', label: '提示' },
  { value: 'warning', label: '注意' },
] as const

export function CalloutView({ node, updateAttributes }: NodeViewProps) {
  const isExample = node.type.name === 'example'
  const title = String(node.attrs.title ?? (isExample ? '例题' : '重点提示'))
  const tone = String(node.attrs.tone ?? 'tip')
  return <NodeViewWrapper
    className={isExample ? 'nb-example-block' : `nb-callout-block nb-callout-${tone}`}
    data-type={node.type.name}
    data-tone={isExample ? undefined : tone}
  >
    <div className="nb-callout-head" contentEditable={false}>
      <span className="nb-callout-icon" aria-hidden="true">{isExample ? '✎' : tone === 'warning' ? '!' : '✦'}</span>
      <input
        className="nb-callout-title"
        value={title}
        aria-label={isExample ? '例题标题' : '提示标题'}
        maxLength={80}
        onChange={(event) => updateAttributes({ title: event.target.value })}
      />
      {!isExample && <select
        className="nb-callout-tone"
        aria-label="提示类型"
        value={tone}
        onChange={(event) => updateAttributes({ tone: event.target.value })}
      >
        {TONES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>}
    </div>
    <NodeViewContent className="nb-callout-content" />
  </NodeViewWrapper>
}
