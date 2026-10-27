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
  const statusLabel = source.source_status === 'stale' ? ' · 来源已更新' : source.source_status === 'unavailable' ? ' · 来源已不可用' : ''
  if (source.source_type === 'web' && source.url) {
    return (
      <a className="source-card web-source-card" href={source.url} target="_blank" rel="noreferrer">
        <span className="source-card-icon" aria-hidden="true">↗</span>
        <span className="source-card-body">
        <span className="source-card-meta">
            网络补充 · {source.site_name}
          {statusLabel}
            {source.published_at ? ` · 发布于 ${source.published_at}` : ''}
            {source.retrieved_at ? ` · 检索于 ${new Date(source.retrieved_at).toLocaleDateString('zh-CN')}` : ''}
          </span>
          <strong>{source.title}</strong>
          <small>{source.snippet}</small>
        </span>
      </a>
    )
  }
  if (source.notebook_id || source.document_block_id || source.block_id) {
    const locator = source.locator && typeof source.locator === 'object' ? source.locator : null
    const locatorLabel = typeof locator?.['location_label'] === 'string'
      ? locator['location_label'] as string
      : source.document_block_id ? '资料原文片段' : 'Notebook 正文'
    return <button className={`source-card notebook-source-card${source.source_status === 'stale' ? ' is-stale' : ''}${source.source_status === 'unavailable' ? ' is-unavailable' : ''}`} type="button" onClick={onOpen} disabled={!onOpen || source.source_status === 'unavailable'}>
      <span className="source-card-icon" aria-hidden="true">▤</span>
      <span className="source-card-body">
        <span className="source-card-meta">{source.notebook_title ?? source.lecture_title ?? '课程内容'} · {locatorLabel}{statusLabel}</span>
        <strong>{source.title ?? '回答依据'}</strong>
        <small>{source.snippet}</small>
      </span>
    </button>
  }
  if (!source.material_id || !source.page_number) return null
  return (
    <div className={source.source_status === 'stale' ? 'source-citation is-stale' : source.source_status === 'unavailable' ? 'source-citation is-unavailable' : undefined}>
    {statusLabel && <small className="source-citation-status">{statusLabel.slice(3).trim()}</small>}
    <SourceCard
      title={source.lecture_title ?? '课程资料'}
      pageNumber={source.page_number}
      locationLabel={source.location_label}
      quote={source.snippet}
      onOpen={source.source_status === 'unavailable' ? undefined : onOpen}
    />
    </div>
  )
}
