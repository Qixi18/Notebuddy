import { useEffect, useRef, useState, type FormEvent } from 'react'

import { api } from '../../api'
import type { TermExplanation } from '../../types'

/** 术语原文说明弹层：从旧左栏折叠面板迁来，功能不变 */
export function TermDialog({ open, onClose, courseId }: {
  open: boolean
  onClose: () => void
  courseId?: string
}) {
  const [term, setTerm] = useState('')
  const [discipline, setDiscipline] = useState('')
  const [explanation, setExplanation] = useState<TermExplanation>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  async function explain(event: FormEvent) {
    event.preventDefault()
    if (!courseId || !term.trim() || busy) return
    try {
      setBusy(true)
      setError(undefined)
      setExplanation(await api.explainTerm(courseId, term.trim(), discipline.trim() || undefined))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '术语解释失败')
      setExplanation(undefined)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="workspace-dialog-backdrop" onClick={onClose}>
      <div
        className="workspace-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="术语原文说明"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="workspace-dialog-head">
          <h2>术语原文说明</h2>
          <button type="button" onClick={onClose} aria-label="关闭术语说明">×</button>
        </header>
        <p className="workspace-dialog-note">
          输入课程中的术语，查看原文、常见译法和学科语境。没有可核验出处时会明确标记不确定。
        </p>
        <form className="workspace-term-form" onSubmit={(event) => void explain(event)}>
          <input
            ref={inputRef}
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            maxLength={200}
            placeholder="例如：dependency injection"
            aria-label="术语"
          />
          <input
            value={discipline}
            onChange={(event) => setDiscipline(event.target.value)}
            maxLength={100}
            placeholder="学科（可选）"
            aria-label="学科"
          />
          <button className="secondary-button" type="submit" disabled={!term.trim() || busy}>
            {busy ? '查询中…' : '解释术语'}
          </button>
        </form>
        {error && <p className="form-error" role="alert">{error}</p>}
        {explanation && (
          <div className={`workspace-term-result${explanation.uncertain ? ' is-uncertain' : ''}`} role="status">
            <strong>{explanation.original}{explanation.discipline ? ` · ${explanation.discipline}` : ''}</strong>
            {explanation.common_translations.length > 0 && (
              <span>常见译法：{explanation.common_translations.join('、')}</span>
            )}
            <p>{explanation.explanation}</p>
            <small>{explanation.source_note}{explanation.uncertain ? ' · 不确定' : ''}</small>
            {explanation.sources?.map((source) => (
              <small key={`${source.material_id}-${source.page_number}`}>
                课程来源：{source.lecture_title} · 第 {source.page_number} 页 · {source.snippet}
              </small>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
