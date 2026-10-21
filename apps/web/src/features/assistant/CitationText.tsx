import { useMemo } from 'react'

import type { AssistantSource } from '../../types'
import { parseCitations } from './citations'
import { AssistantMessageMarkdown } from './AssistantMessageContent'

/**
 * 把带来源标记的正文渲染成 Markdown + 角标徽标。
 * 角标是段落级（标记在哪个段落，徽标就落在该段落末尾），点击回调给依据台定位。
 */
export function CitationText({ content, sources = [], onCite }: {
  content: string
  sources?: AssistantSource[]
  onCite?: (no: number) => void
}) {
  const { paragraphs } = useMemo(() => parseCitations(content, sources), [content, sources])
  return (
    <>
      {paragraphs.map((paragraph, index) => {
        /* 正文按空行切块，标题块需要更大的上间距（见 course-assistant.css 的节奏规则） */
        const isHeading = /^#{1,6}\s/.test(paragraph.text.trimStart())
        return (
          <div className={`cite-paragraph${isHeading ? ' is-heading' : ''}`} key={index}>
            <AssistantMessageMarkdown content={paragraph.text} />
            {paragraph.flags.map((flag) => (
              <span className="cite-flag" key={`${index}-${flag}`}>{flag}</span>
            ))}
            {paragraph.refs.length > 0 && (
              <span className="cite-refs">
                {paragraph.refs.map((ref) => (
                  <button
                    key={ref.no}
                    type="button"
                    className="cite-ref"
                    aria-label={`查看依据 ${ref.no}：${ref.title}${ref.page ? ` 第 ${ref.page} 页` : ''}`}
                    onClick={() => onCite?.(ref.no)}
                  >
                    {ref.no}
                  </button>
                ))}
              </span>
            )}
          </div>
        )
      })}
    </>
  )
}
