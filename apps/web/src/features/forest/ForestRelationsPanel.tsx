import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api'
import type { ForestCourse, NotebookRelation, RelationType } from './types'
import { relationLabels } from './types'

export function ForestRelationsPanel({
  courses,
  relations,
  onClose,
  onChanged,
  selectedRelationId,
  onLocate,
}: {
  courses: ForestCourse[]
  relations: NotebookRelation[]
  onClose: () => void
  onChanged: () => void
  selectedRelationId?: string
  onLocate?: (relation: NotebookRelation) => void
}) {
  const [notebooks, setNotebooks] = useState<Array<{
    id: string; title: string; courseId: string; sections: Array<{ id: string; title: string }>
  }>>([])
  const [sourceCourse, setSourceCourse] = useState('')
  const [targetCourse, setTargetCourse] = useState('')
  const [sourceNotebook, setSourceNotebook] = useState('')
  const [targetNotebook, setTargetNotebook] = useState('')
  const [sourceBlock, setSourceBlock] = useState('')
  const [targetBlock, setTargetBlock] = useState('')
  const [relationType, setRelationType] = useState<RelationType>('related')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    const ids = [...new Set([sourceCourse, targetCourse].filter(Boolean))]
    void Promise.all(ids.map(async (courseId) => {
      const tree = await api.getCourseTree(courseId)
      return tree.notebooks.filter(book => book.course_id === courseId).map(book => ({
        id: book.id, title: book.title, courseId,
        sections: book.chapters.filter(chapter => !chapter.deleted_at).flatMap(chapter => chapter.sections)
          .concat(book.historical_sections).map(section => ({ id: section.block_id ?? section.id, title: section.title })),
      }))
    })).then((groups) => { if (active) setNotebooks(groups.flat()) })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '笔记目录读取失败') })
    return () => { active = false }
  }, [sourceCourse, targetCourse])

  const ordered = useMemo(() => [...relations].sort((a, b) =>
    Number(b.id === selectedRelationId) - Number(a.id === selectedRelationId)), [relations, selectedRelationId])

  const sourceOptions = useMemo(
    () => notebooks.filter((book) => book.courseId === sourceCourse),
    [notebooks, sourceCourse],
  )
  const targetOptions = useMemo(
    () => notebooks.filter((book) => book.courseId === targetCourse && book.courseId !== sourceCourse),
    [notebooks, targetCourse, sourceCourse],
  )

  async function create() {
    if (!sourceNotebook || !targetNotebook) { setError('请选择两本不同课程中的笔记'); return }
    if (!reason.trim()) { setError('请填写关联依据'); return }
    setBusy(true)
    try {
      await api.createForestRelation({
        source_notebook_id: sourceNotebook, target_notebook_id: targetNotebook,
        relation_type: relationType, reason: reason.trim(),
        source_block_id: sourceBlock || null, target_block_id: targetBlock || null,
      })
      setReason('')
      setSourceNotebook('')
      setTargetNotebook('')
      setSourceBlock('')
      setTargetBlock('')
      setError(undefined)
      onChanged()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '关系创建失败')
    } finally { setBusy(false) }
  }

  async function remove(id: string) {
    setBusy(true)
    try { await api.deleteForestRelation(id); onChanged() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '关系删除失败') }
    finally { setBusy(false) }
  }

  async function confirm(id: string) {
    setBusy(true)
    try { await api.refreshForestRelation(id); setError(undefined); onChanged() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '关联核对失败') }
    finally { setBusy(false) }
  }

  return (
    <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="跨课关联">
      <div className="nb-modal is-wide">
        <div className="nb-modal-head"><h2>跨课关联</h2><button type="button" onClick={onClose} aria-label="关闭">×</button></div>
        <p className="muted-copy">连接不同课程的笔记，记录它们之间的联系和依据。</p>
        <div className="forest-relation-form">
          <label>来源课程<select value={sourceCourse} onChange={(event) => { setSourceCourse(event.target.value); setSourceNotebook(''); setSourceBlock('') }}><option value="">选择课程</option>{courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.name}</option>)}</select></label>
          <label>来源笔记<select value={sourceNotebook} onChange={(event) => { setSourceNotebook(event.target.value); setSourceBlock('') }}><option value="">选择笔记</option>{sourceOptions.map((book) => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>
          <label>来源小节<select value={sourceBlock} onChange={event => setSourceBlock(event.target.value)}><option value="">整本笔记</option>{sourceOptions.find(book => book.id === sourceNotebook)?.sections.map(section => <option key={section.id} value={section.id}>{section.title}</option>)}</select></label>
          <label>关系类型<select value={relationType} onChange={(event) => setRelationType(event.target.value as RelationType)}>{Object.entries(relationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>目标课程<select value={targetCourse} onChange={(event) => { setTargetCourse(event.target.value); setTargetNotebook(''); setTargetBlock('') }}><option value="">选择课程</option>{courses.filter((course) => course.course_id !== sourceCourse).map((course) => <option key={course.course_id} value={course.course_id}>{course.name}</option>)}</select></label>
          <label>目标笔记<select value={targetNotebook} onChange={(event) => { setTargetNotebook(event.target.value); setTargetBlock('') }}><option value="">选择笔记</option>{targetOptions.map((book) => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>
          <label>目标小节<select value={targetBlock} onChange={event => setTargetBlock(event.target.value)}><option value="">整本笔记</option>{targetOptions.find(book => book.id === targetNotebook)?.sections.map(section => <option key={section.id} value={section.id}>{section.title}</option>)}</select></label>
          <label className="forest-relation-reason">关联依据<textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} maxLength={4000} /></label>
          <button type="button" className="primary-button" disabled={busy} onClick={() => void create()}>{busy ? '保存中…' : '建立关联'}</button>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="forest-relation-list">
          {ordered.length === 0 ? <p className="muted-copy">还没有跨课关联。</p> : ordered.map((relation) => (
            <article className="forest-relation-row" key={relation.id}>
              <h3>{relation.source_title} → {relation.target_title}</h3>
              <Link to={`/courses/${encodeURIComponent(relation.source_course_id)}/notebooks/${encodeURIComponent(relation.source_notebook_id)}${relation.source_block_id ? `?section=${encodeURIComponent(relation.source_block_id)}` : ''}`}>{relation.source_course_name} · {relation.source_title}</Link>
              <strong>{relationLabels[relation.relation_type]} · {relation.origin === 'ai' ? '自动关联（模型推断）' : '手动关联'}</strong>
              <Link to={`/courses/${encodeURIComponent(relation.target_course_id)}/notebooks/${encodeURIComponent(relation.target_notebook_id)}${relation.target_block_id ? `?section=${encodeURIComponent(relation.target_block_id)}` : ''}`}>{relation.target_course_name} · {relation.target_title}</Link>
              <small>{relation.reason}</small>
              {(relation.source_block_id || relation.target_block_id) && <RelationSources relation={relation} />}
              {relation.stale && <><p role="status">关联小节的正文已变化，请核对关联依据。</p><button type="button" disabled={busy} onClick={() => void confirm(relation.id)}>确认关联仍有效</button></>}
              {onLocate && <button type="button" className="text-button" onClick={() => onLocate(relation)}>在树中定位端点</button>}
              <button type="button" className="text-button" disabled={busy} onClick={() => void remove(relation.id)}>{relation.origin === 'ai' ? '隐藏关联' : '删除'}</button>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}

function RelationSources({ relation }: { relation: NotebookRelation }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<Array<{ asset_name: string; quote: string; page_number: number; parse_run_id: string; status: string }>>()
  const [error, setError] = useState<string>()
  useEffect(() => {
    if (!open) return
    let active = true
    setRows(undefined)
    setError(undefined)
    void Promise.all([
      relation.source_block_id ? api.getNotebookBlockSources(relation.source_notebook_id, relation.source_block_id) : Promise.resolve([]),
      relation.target_block_id ? api.getNotebookBlockSources(relation.target_notebook_id, relation.target_block_id) : Promise.resolve([]),
    ]).then(groups => { if (active) setRows(groups.flat()) })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '来源读取失败') })
    return () => { active = false }
  }, [open, relation.source_notebook_id, relation.target_notebook_id, relation.source_block_id,
    relation.target_block_id, relation.source_fingerprint, relation.target_fingerprint, relation.stale])
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>核对两端来源</summary>
    {open && (error ? <p role="alert">{error}</p> : !rows ? <p role="status">正在读取来源…</p>
      : rows.length === 0 ? <p>这些小节尚未关联原始资料，请直接核对笔记正文。</p>
        : rows.map((row, index) => <blockquote key={`${row.parse_run_id}:${index}`}>
          <p>{row.quote}</p><small>{row.asset_name} · 第 {row.page_number} 页{row.status !== 'active' ? ' · 来源待核对' : ''}</small>
        </blockquote>))}
  </details>
}
