import { useEffect, useMemo, useRef, useState } from 'react'

import type { AssistantSource } from '../../types'
import { parseCitations, type CiteRef } from './citations'

/**
 * 回答卡底部的依据行：一行来源 chips + 可展开的原文。
 * 角标编号按正文首次引用顺序生成，与 chips 编号一一对应。
 * 点正文角标会滚动到这里、展开原文并高亮对应 chip（否则依据在长回答底部，点了像没反应）。
 */
export function SourcesRow({ content, sources, activeNo, focus, onActive, onOpenMaterial, onOpenNotebook }: {
  content: string
  sources: AssistantSource[]
  activeNo?: number
  /** 正文角标点击请求：值变化即定位到对应 chip（连点同一个角标也会重定位） */
  focus?: { no: number; seq: number }
  onActive: (no: number) => void
  onOpenMaterial?: (materialId: string, page: number) => void
  onOpenNotebook?: (notebookId: string, blockId?: string, assetId?: string, page?: number) => void
}) {
  const [open, setOpen] = useState(false)
  const chipRefs = useRef(new Map<number, HTMLButtonElement>())

  const refs = useMemo<CiteRef[]>(() => {
    if (sources.length === 0) return []
    const parsed = parseCitations(content, sources)
    const seen = new Map<number, CiteRef>()
    for (const paragraph of parsed.paragraphs) {
      for (const ref of paragraph.refs) if (!seen.has(ref.no)) seen.set(ref.no, ref)
    }
    for (const [sourceIndex, source] of sources.entries()) {
      if (!source.notebook_id || [...seen.values()].some((ref) => ref.sourceIndex === sourceIndex)) continue
      const no = Math.max(0, ...seen.keys()) + 1
      seen.set(no, { no, kind: 'notebook', sourceIndex, title: source.lecture_title ?? source.title ?? 'Notebook 正文' })
    }
    return [...seen.values()].sort((a, b) => a.no - b.no)
  }, [content, sources])

  useEffect(() => {
    if (!focus) return
    setOpen(true)
    /* 等展开后的布局稳定再滚，避免定位到旧位置 */
    const raf = requestAnimationFrame(() => {
      const chip = chipRefs.current.get(focus.no)
      if (!chip) return
      /* 只滚对话列，不用 scrollIntoView —— 它会连带滚动所有祖先，
         移动端会把整页往下拽一屏（见 AssistantThread 里的同类注释）。 */
      const thread = chip.closest('.workspace-thread')
      if (!(thread instanceof HTMLElement)) return
      const chipRect = chip.getBoundingClientRect()
      const threadRect = thread.getBoundingClientRect()
      const delta = (chipRect.top - threadRect.top)
        - (thread.clientHeight / 2 - chipRect.height / 2)
      if (Math.abs(delta) < 4) return
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      thread.scrollBy({ top: delta, behavior: reduce ? 'auto' : 'smooth' })
    })
    return () => cancelAnimationFrame(raf)
  }, [focus])

  if (refs.length === 0) return null

  return (
    <section className="workspace-sources" aria-label="回答依据">
      <div className="workspace-sources-head">
        <span className="workspace-sources-label">依据 <b>{refs.length}</b> 段</span>
        <button
          type="button"
          className="workspace-sources-toggle"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >{open ? '收起原文' : '查看原文'} <span aria-hidden="true">→</span></button>
      </div>

      <div className="workspace-source-row">
        {refs.map((ref) => (
          <button
            key={ref.no}
            ref={(el) => {
              if (el) chipRefs.current.set(ref.no, el)
              else chipRefs.current.delete(ref.no)
            }}
            type="button"
            className={`workspace-source-chip${activeNo === ref.no ? ' is-active' : ''}`}
            aria-pressed={activeNo === ref.no}
            onClick={() => onActive(ref.no)}
            title={`${ref.title}${ref.page ? ` · 第 ${ref.page} 页` : ''}`}
          >
            <i aria-hidden="true">{ref.no}</i>
            {ref.title}{ref.page ? ` · p.${ref.page}` : ''}
          </button>
        ))}
      </div>

      {open && (
        <ul className="workspace-source-detail">
          {refs.map((ref) => {
            const source = sources[ref.sourceIndex]
            return (
              <li key={ref.no} className={activeNo === ref.no ? 'is-active' : undefined}>
                <span className="workspace-source-detail-no" aria-hidden="true">{ref.no}</span>
                <div>
                  <strong>
                    {source?.lecture_title ?? source?.title ?? '来源'}
                    {source?.page_number ? ` · p.${source.page_number}` : ''}
                  </strong>
                  {source?.snippet && <p>{source.snippet}</p>}
                {source?.notebook_id && onOpenNotebook && (
                  <button type="button" className="workspace-source-open"
                    onClick={() => onOpenNotebook(source.notebook_id!, source.block_id ?? undefined,
                      source.asset_id ?? undefined, source.page_number ?? undefined)}>
                    {source.asset_id ? '查看原始资料 →' : '打开 Notebook →'}
                  </button>
                )}
                {source?.material_id && source.page_number && onOpenMaterial && (
                    <button
                      type="button"
                      className="workspace-source-open"
                      onClick={() => onOpenMaterial(source.material_id!, source.page_number!)}
                    >打开课件 →</button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
