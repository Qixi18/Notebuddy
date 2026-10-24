import { useEffect, useMemo, useRef } from 'react'

import type { ConversationMessage } from '../../types'
import { noEvidenceLabels } from './answerMeta'

/** support_level 的前端文案，取值与 apps/backend/app/ai/evidence.py 对应 */
const SUPPORT_LABELS: Record<string, { label: string; tone: string }> = {
  direct: { label: '支撑', tone: 'direct' },
  related: { label: '部分支撑', tone: 'related' },
  supplement: { label: '网络补充', tone: 'supplement' },
  unverified: { label: '未核验', tone: 'unverified' },
}

type NumberedSource = { source: NonNullable<ConversationMessage['sources']>[number]; no: number }

/** 依据台：回答来源常驻右栏，点角标就地定位，不打断对话 */
export function EvidencePanel({ message, open, onToggle, activeSource, onActiveChange, onOpenMaterial }: {
  message?: ConversationMessage
  open: boolean
  onToggle: () => void
  /** 1 起，等于来源在 message.sources 中的位置 */
  activeSource?: number
  onActiveChange: (no: number | undefined) => void
  onOpenMaterial: (materialId: string, page?: number) => void
}) {
  const cardRefs = useRef(new Map<number, HTMLLIElement>())
  const sources = useMemo(() => message?.sources ?? [], [message])

  useEffect(() => {
    if (!open || activeSource === undefined) return
    const node = cardRefs.current.get(activeSource)
    /* jsdom 没有实现 scrollIntoView，缺函数时跳过滚动 */
    if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'nearest' })
  }, [activeSource, open, message?.id])

  const grouped = useMemo(() => {
    const course: NumberedSource[] = []
    const web: NumberedSource[] = []
    sources.forEach((source, index) => {
      const item = { source, no: index + 1 }
      if (source.source_type === 'web') web.push(item)
      else course.push(item)
    })
    return { course, web }
  }, [sources])

  return (
    <>
      <aside
        className={`workspace-evidence${open ? ' is-open' : ''}`}
        aria-label="回答依据"
        inert={!open}
      >
        <div className="workspace-evidence-inner">
          <header className="workspace-evidence-head">
            <h2>回答依据 <span className="workspace-evidence-count">{sources.length}</span></h2>
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              aria-label={open ? '收起依据栏' : '展开依据栏'}
            >
              <span aria-hidden="true">{open ? '»' : '«'}</span>
            </button>
          </header>

          <div className="workspace-evidence-body">
            {sources.length === 0 ? (
              <p className="workspace-evidence-empty">
                {message
                  ? (message.mode && noEvidenceLabels[message.mode]) || '这轮回答没有可核验的原文依据。'
                  : '还没有回答。提问后，回答引用的课程原文与网络补充会出现在这里。'}
              </p>
            ) : (
              <>
                {grouped.course.length > 0 && (
                  <section className="workspace-evidence-group" aria-label="课程资料">
                    <span className="workspace-evidence-group-label">课程资料 {grouped.course.length}</span>
                    <ol className="workspace-evidence-list">
                      {grouped.course.map(({ source, no }) => (
                        <EvidenceCard
                          key={`course-${no}`}
                          item={{ source, no }}
                          active={activeSource === no}
                          onActive={() => onActiveChange(no)}
                          register={(node) => { if (node) cardRefs.current.set(no, node); else cardRefs.current.delete(no) }}
                          onOpenMaterial={onOpenMaterial}
                        />
                      ))}
                    </ol>
                  </section>
                )}
                {grouped.web.length > 0 && (
                  <section className="workspace-evidence-group" aria-label="网络补充">
                    <span className="workspace-evidence-group-label">网络补充 {grouped.web.length}</span>
                    <ol className="workspace-evidence-list">
                      {grouped.web.map(({ source, no }) => (
                        <EvidenceCard
                          key={`web-${no}`}
                          item={{ source, no }}
                          active={activeSource === no}
                          onActive={() => onActiveChange(no)}
                          register={(node) => { if (node) cardRefs.current.set(no, node); else cardRefs.current.delete(no) }}
                          onOpenMaterial={onOpenMaterial}
                        />
                      ))}
                    </ol>
                  </section>
                )}
              </>
            )}
          </div>

          {sources.length > 0 && (
            <footer className="workspace-evidence-legend">
              支撑 = 原文直接支撑 · 部分支撑 = 相关段落 · 网络补充 = 联网结果 · 未核验 = 无直接出处
            </footer>
          )}
        </div>
      </aside>
      {open && <div className="workspace-evidence-backdrop" onClick={onToggle} aria-hidden="true" />}
    </>
  )
}

function EvidenceCard({ item, active, onActive, register, onOpenMaterial }: {
  item: NumberedSource
  active: boolean
  onActive: () => void
  register: (node: HTMLLIElement | null) => void
  onOpenMaterial: (materialId: string, page?: number) => void
}) {
  const { source, no } = item
  const support = source.support_level ? SUPPORT_LABELS[source.support_level] : undefined
  const isWeb = source.source_type === 'web'
  return (
    <li
      ref={register}
      className={`workspace-evidence-card${active ? ' is-active' : ''}`}
      onClick={onActive}
    >
      <span className="workspace-evidence-no" aria-hidden="true">{no}</span>
      <div className="workspace-evidence-cardbody">
        <strong>{isWeb ? (source.title ?? '网络来源') : (source.lecture_title ?? '课程资料')}</strong>
        <span className="workspace-evidence-meta">
          {isWeb
            ? `${source.site_name ?? '网络'}${source.published_at ? ` · ${new Date(source.published_at).toLocaleDateString('zh-CN')}` : ''}`
            : `第 ${source.page_number ?? '?'} 页${source.location_label ? ` · ${source.location_label}` : ''}`}
        </span>
        {source.snippet && <p className="workspace-evidence-snippet">{source.snippet}</p>}
      </div>
      <div className="workspace-evidence-cardfoot">
        {support && <span className={`workspace-evidence-support is-${support.tone}`}>{support.label}</span>}
        {isWeb && source.url && (
          <a className="workspace-evidence-open" href={source.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
            打开来源 <span aria-hidden="true">↗</span>
          </a>
        )}
        {!isWeb && source.material_id && source.page_number && (
          <button
            type="button"
            className="workspace-evidence-open"
            onClick={(event) => { event.stopPropagation(); onOpenMaterial(source.material_id!, source.page_number ?? undefined) }}
          >
            打开课件 <span aria-hidden="true">→</span>
          </button>
        )}
      </div>
    </li>
  )
}
