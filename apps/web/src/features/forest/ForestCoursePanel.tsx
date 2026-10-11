import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { Notebook, NotebookSection } from '../../types'
import {
  levelLabels,
  stateLabels,
  type ForestCourse,
  type ForestJob,
  type ForestLevel,
  type LearningState,
} from './types'

export function ForestCoursePanel({
  course,
  book,
  expanded,
  onExpand,
  onClose,
  onUpdated,
  onOpen,
  onFit,
  onJob,
}: {
  course: ForestCourse
  book?: Notebook
  expanded: Set<string>
  onExpand: (id: string) => void
  onClose: () => void
  onUpdated: (course: ForestCourse) => void
  onOpen: (section: NotebookSection) => void
  onFit: () => void
  onJob: (job: ForestJob) => void
}) {
  const [semester, setSemester] = useState(course.semester?.toString() ?? '')
  const [level, setLevel] = useState(course.level)
  const [state, setState] = useState(course.learning_state)
  const [position, setPosition] = useState(course.position)
  const [prerequisites, setPrerequisites] = useState(course.prerequisites.join('、'))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      onUpdated(
        await api.updateForestCourse(course.course_id, {
          expected_revision: course.revision,
          semester: semester ? Number(semester) : null,
          level,
          learning_state: state,
          position,
          prerequisites: prerequisites
            .split(/[,，、]/)
            .map((value) => value.trim())
            .filter(Boolean),
        }),
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程设置保存失败')
    } finally {
      setBusy(false)
    }
  }
  async function suggest() {
    setBusy(true)
    setError(undefined)
    try {
      onJob(await api.suggestForestRelations(course.course_id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '关联建议生成失败')
    } finally {
      setBusy(false)
    }
  }
  const chapters = book
    ? [
        ...book.chapters,
        ...(book.historical_sections.length
          ? [{ id: 'history', title: '历史整理', sections: book.historical_sections }]
          : []),
      ]
    : []
  return (
    <aside className="forest-course-panel" aria-label={`${course.name}课程树`}>
      <header>
        <div>
          <small>
            {course.semester ? `第 ${course.semester} 学期` : '学期未安排'} ·{' '}
            {levelLabels[course.level]}
          </small>
          <h2>{course.name}</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="退出课程聚焦">
          ×
        </button>
      </header>
      <p className="forest-course-state">
        <span className={`forest-state-dot forest-state-${course.learning_state}`} />
        {stateLabels[course.learning_state]}
        <small>学习状态由你确认</small>
      </p>
      <div className="forest-course-reading-links">
        <Link to={`/courses/${course.course_id}/notebook`}>整本阅读</Link>
        <Link to={`/courses/${course.course_id}/materials`}>上传下一讲</Link>
        <button type="button" onClick={onFit}>
          适应展开内容
        </button>
      </div>
      {error && (
        <p className="forest-error" role="alert">
          {error}
        </p>
      )}
      <section className="forest-chapter-list" aria-label="课程讲次">
        <h3>展开讲次，寻找笔记叶子</h3>
        {!book && <p role="status">正在读取讲次目录…</p>}
        {book && !chapters.length && <p>这棵树还没有笔记。上传第一讲课件，让知识开始生长。</p>}
        {chapters.map((chapter) => (
          <div key={chapter.id} className="forest-chapter">
            <button
              className="forest-chapter-toggle"
              type="button"
              aria-expanded={expanded.has(chapter.id)}
              onClick={() => onExpand(chapter.id)}
            >
              <span aria-hidden="true">{expanded.has(chapter.id) ? '−' : '＋'}</span>
              <strong>{chapter.title}</strong>
              <small>{chapter.sections.length} 叶</small>
            </button>
            {expanded.has(chapter.id) && (
              <div className="forest-chapter-notes">
                {chapter.sections.map((section) => (
                  <button key={section.id} type="button" onClick={() => onOpen(section)}>
                    <span aria-hidden="true">❧</span>
                    {section.title}
                    {section.user_locked && <small>已编辑</small>}
                  </button>
                ))}
                {!chapter.sections.length && <p>暂无笔记小节，请查看资料处理状态。</p>}
              </div>
            )}
          </div>
        ))}
      </section>
      <details className="forest-course-settings">
        <summary>调整学期、位置与学习状态</summary>
        <form onSubmit={(event) => void save(event)}>
          <div className="forest-form-pair">
            <label>
              学期
              <input
                type="number"
                min="1"
                max="30"
                value={semester}
                placeholder="未安排"
                onChange={(event) => setSemester(event.target.value)}
              />
            </label>
            <label>
              排列顺序
              <input
                type="number"
                min="0"
                value={position}
                onChange={(event) => setPosition(Number(event.target.value))}
              />
            </label>
          </div>
          <label>
            课程层级
            <select value={level} onChange={(event) => setLevel(event.target.value as ForestLevel)}>
              {Object.entries(levelLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            学习状态
            <select
              value={state}
              onChange={(event) => setState(event.target.value as LearningState)}
            >
              {Object.entries(stateLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <p className="forest-settings-hint">“已完成”表示课程进度，不代表已掌握所有知识。</p>
          <label>
            先修课程
            <input
              value={prerequisites}
              placeholder="用逗号分隔课程名称"
              onChange={(event) => setPrerequisites(event.target.value)}
            />
          </label>
          <button className="forest-action" type="submit" disabled={busy}>
            {busy ? '正在保存…' : '保存课程设置'}
          </button>
        </form>
      </details>
      <button
        className="forest-suggest-button"
        type="button"
        disabled={busy || course.note_count === 0}
        onClick={() => void suggest()}
      >
        生成跨课程关联建议
      </button>
    </aside>
  )
}
