import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

import { SourceCard } from '../../components/SourceCard'
import type { AssistantSource } from '../../types'

export function AssistantMessageMarkdown({ content }: { content: string }) {
  return <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>{content}</ReactMarkdown>
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
