import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api'
import type { NotebookSection, NoteSourceRef } from '../../types'
import { ForestDialog } from './ForestDialog'
import {
  relationLabels,
  type CrossCourseRelation,
  type ForestCourse,
  type RelationType,
} from './types'

// Relation summaries do not carry a material ID; a section-only URL resolves the exact note in its real chapter.
function forestNotePath(courseId: string, section: { id: string; material_id: string | null }) {
  return `/courses/${courseId}/notes/${encodeURIComponent(section.id)}`
}

function RelationEvidence({ relation }: { relation: CrossCourseRelation }) {
  const [sources, setSources] = useState<NoteSourceRef[]>()
  const [error, setError] = useState<string>()
  return (
    <details
      className="forest-relation-evidence"
      onToggle={(event) => {
        if (!event.currentTarget.open || sources || error) return
        void Promise.all([
          api.getNoteSources(relation.source_note_id),
          api.getNoteSources(relation.target_note_id),
        ])
          .then(([a, b]) =>
            setSources(
              [...a, ...b].filter((source) =>
                [...relation.source_ref_ids, ...relation.target_ref_ids].includes(source.id),
              ),
            ),
          )
          .catch((cause) => setError(cause instanceof Error ? cause.message : '来源读取失败'))
      }}
    >
      <summary>
        核对两端来源 · {relation.source_ref_ids.length + relation.target_ref_ids.length} 条
      </summary>
      {error ? (
        <p role="alert">{error}</p>
      ) : sources ? (
        sources.length ? (
          sources.map((source) => (
            <blockquote key={source.id}>
              <p>{source.quote}</p>
              <small>
                {source.location_label ?? `第 ${source.page_number} 页`}
                {source.status && source.status !== 'valid' ? ` · ${source.status}` : ''}
              </small>
            </blockquote>
          ))
        ) : (
          <p>没有当前可核对的来源，请打开笔记检查引用。</p>
        )
      ) : (
        <p role="status">正在读取来源…</p>
      )}
    </details>
  )
}

export function ForestRelationsPanel({
  relations,
  courses,
  onChange,
  onClose,
}: {
  relations: CrossCourseRelation[]
  courses: ForestCourse[]
  onChange: () => void
  onClose: () => void
}) {
  const [filter, setFilter] = useState<'pending' | 'confirmed' | 'rejected'>('pending')
  const [manual, setManual] = useState(false)
  const [sourceCourse, setSourceCourse] = useState('')
  const [targetCourse, setTargetCourse] = useState('')
  const [sourceSections, setSourceSections] = useState<NotebookSection[]>([])
  const [targetSections, setTargetSections] = useState<NotebookSection[]>([])
  const [sourceNote, setSourceNote] = useState('')
  const [targetNote, setTargetNote] = useState('')
  const [type, setType] = useState<RelationType>('related')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  useEffect(() => {
    let active = true
    setSourceSections([])
    setTargetSections([])
    setSourceNote('')
    setTargetNote('')
    if (!manual || !sourceCourse || !targetCourse || sourceCourse === targetCourse) return
    setLoading(true)
    void Promise.all([api.getNotebook(sourceCourse), api.getNotebook(targetCourse)])
      .then(([a, b]) => {
        if (!active) return
        setSourceSections(a.chapters.flatMap((c) => c.sections).concat(a.historical_sections))
        setTargetSections(b.chapters.flatMap((c) => c.sections).concat(b.historical_sections))
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : '笔记目录读取失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [manual, sourceCourse, targetCourse])
  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setError(undefined)
    try {
      await action()
      onChange()
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '关联操作失败')
      return false
    } finally {
      setBusy(false)
    }
  }
  async function create(event: FormEvent) {
    event.preventDefault()
    if (
      await act(() =>
        api.createForestRelation({
          source_note_id: sourceNote,
          target_note_id: targetNote,
          relation_type: type,
          reason: reason.trim(),
        }),
      )
    ) {
      setManual(false)
      setFilter('confirmed')
    }
  }
  const available = courses.filter((course) => course.note_count > 0)
  return (
    <ForestDialog title="跨课程藤蔓" onClose={onClose} wide>
      <p className="forest-dialog-intro">
        连接两门课程中真实的笔记。AI 建议经过确认后才会出现在森林里。
      </p>
      <div className="forest-relation-toolbar">
        <div role="group" aria-label="关联状态">
          {(['pending', 'confirmed', 'rejected'] as const).map((status) => (
            <button
              type="button"
              className={filter === status && !manual ? 'active' : ''}
              onClick={() => {
                setFilter(status)
                setManual(false)
              }}
              key={status}
            >
              {status === 'pending' ? '待确认' : status === 'confirmed' ? '已连接' : '已忽略'} (
              {relations.filter((r) => r.status === status).length})
            </button>
          ))}
        </div>
        <button type="button" className="forest-action" onClick={() => setManual(true)}>
          手动连接笔记
        </button>
      </div>
      {error && (
        <p role="alert" className="forest-error">
          {error}
        </p>
      )}
      {manual ? (
        <form className="forest-manual-relation" onSubmit={(event) => void create(event)}>
          {available.length < 2 && <p>至少两门课程有笔记后，才能建立跨课程藤蔓。</p>}
          <div className="forest-form-pair">
            <label>
              起点课程
              <select
                value={sourceCourse}
                onChange={(event) => setSourceCourse(event.target.value)}
                required
              >
                <option value="">选择课程</option>
                {available.map((course) => (
                  <option value={course.course_id} key={course.course_id}>
                    {course.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              终点课程
              <select
                value={targetCourse}
                onChange={(event) => setTargetCourse(event.target.value)}
                required
              >
                <option value="">选择另一门课程</option>
                {available
                  .filter((course) => course.course_id !== sourceCourse)
                  .map((course) => (
                    <option value={course.course_id} key={course.course_id}>
                      {course.name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          {loading && <p role="status">正在读取笔记目录…</p>}
          <div className="forest-form-pair">
            <label>
              起点笔记
              <select
                value={sourceNote}
                onChange={(event) => setSourceNote(event.target.value)}
                required
                disabled={!sourceSections.length}
              >
                <option value="">选择真实笔记</option>
                {sourceSections.map((section) => (
                  <option value={section.id} key={section.id}>
                    {section.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              终点笔记
              <select
                value={targetNote}
                onChange={(event) => setTargetNote(event.target.value)}
                required
                disabled={!targetSections.length}
              >
                <option value="">选择真实笔记</option>
                {targetSections.map((section) => (
                  <option value={section.id} key={section.id}>
                    {section.title}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            关系
            <select value={type} onChange={(event) => setType(event.target.value as RelationType)}>
              {Object.entries(relationLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            连接理由
            <textarea
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="这两个知识点如何联系？"
            />
          </label>
          <button
            className="forest-action"
            disabled={
              busy || !sourceNote || !targetNote || !reason.trim() || sourceCourse === targetCourse
            }
            type="submit"
          >
            {busy ? '正在连接…' : '建立藤蔓'}
          </button>
        </form>
      ) : (
        <div className="forest-relation-list">
          {relations
            .filter((relation) => relation.status === filter)
            .map((relation) => (
              <article key={relation.id} className="forest-relation-card">
                <span className="forest-relation-kind">
                  {relationLabels[relation.relation_type]} ·{' '}
                  {relation.origin === 'ai' ? 'AI 建议' : '手动连接'}
                </span>
                <h3>
                  {relation.source_title} <span aria-hidden="true">↝</span> {relation.target_title}
                </h3>
                <p className="forest-relation-courses">
                  {relation.source_course_name} / {relation.target_course_name}
                </p>
                <p>{relation.reason}</p>
                <div className="forest-relation-note-links">
                  <a
                    href={forestNotePath(relation.source_course_id, {
                      id: relation.source_note_id,
                      material_id: null,
                    })}
                  >
                    核对起点笔记
                  </a>
                  <a
                    href={forestNotePath(relation.target_course_id, {
                      id: relation.target_note_id,
                      material_id: null,
                    })}
                  >
                    核对终点笔记
                  </a>
                </div>
                {relation.stale && (
                  <p className="forest-stale">笔记已修改，需重新生成并核对关联；当前不绘制藤蔓。</p>
                )}
                <RelationEvidence relation={relation} />
                {relation.stale && (
                  <button
                    className="forest-action"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void act(() =>
                        api.createForestRelation({
                          source_note_id: relation.source_note_id,
                          target_note_id: relation.target_note_id,
                          relation_type: relation.relation_type,
                          reason: relation.reason,
                        }),
                      )
                    }
                  >
                    重新核对并连接
                  </button>
                )}
                <div className="forest-relation-actions">
                  {filter === 'pending' ? (
                    <>
                      <button
                        className="forest-action"
                        type="button"
                        disabled={busy || relation.stale}
                        onClick={() =>
                          void act(() => api.reviewForestRelation(relation.id, 'confirm'))
                        }
                      >
                        确认关联
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void act(() => api.reviewForestRelation(relation.id, 'reject'))
                        }
                      >
                        忽略建议
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void act(() => api.deleteForestRelation(relation.id))}
                    >
                      移除关联
                    </button>
                  )}
                </div>
              </article>
            ))}
          {!relations.some((relation) => relation.status === filter) && (
            <p className="forest-empty-message">
              {filter === 'pending'
                ? '暂时没有待确认的关联。可以选中一门课程，生成跨课程建议。'
                : filter === 'confirmed'
                  ? '还没有跨课程藤蔓。可以手动连接两片笔记叶子。'
                  : '没有已忽略的建议。'}
            </p>
          )}
        </div>
      )}
    </ForestDialog>
  )
}
