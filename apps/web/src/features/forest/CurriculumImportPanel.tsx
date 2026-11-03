import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api'
import { ForestDialog } from './ForestDialog'
import { ProcessingRouteControl, useProcessingRoute } from '../notebook/useProcessingRoute'
import { compareCurriculum, reviewCurriculum } from './curriculumReview'
import {
  levelLabels,
  type CurriculumImport,
  type CurriculumRow,
  type CurriculumRevertImpact,
  type ForestCourse,
  type ForestLevel,
} from './types'

export function CurriculumImportPanel({
  courses,
  onConfirmed,
  onClose,
}: {
  courses: ForestCourse[]
  onConfirmed: () => void
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File>()
  const [current, setCurrent] = useState<CurriculumImport>()
  const [history, setHistory] = useState<CurriculumImport[]>([])
  const [rows, setRows] = useState<CurriculumRow[]>([])
  const [excluded, setExcluded] = useState<string[]>([])
  const [comparisonId, setComparisonId] = useState('')
  const [revertImpact, setRevertImpact] = useState<CurriculumRevertImpact>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const { route, setRoute } = useProcessingRoute()
  useEffect(() => {
    void api
      .listCurriculumImports()
      .then(setHistory)
      .catch((cause) => setError(cause instanceof Error ? cause.message : '导入记录读取失败'))
  }, [])
  const importId = current?.id,
    status = current?.status
  useEffect(() => {
    if (!importId || (status !== 'pending' && status !== 'processing')) return
    let active = true,
      inFlight = false
    const timer = window.setInterval(() => {
      if (inFlight) return
      inFlight = true
      void api
        .getCurriculumImport(importId)
        .then((next) => {
          if (active) {
            setCurrent(next)
            if (next.status === 'preview') setRows(next.rows)
          }
        })
        .catch((cause) => {
          if (active) setError(cause instanceof Error ? cause.message : '任务状态读取失败')
        })
        .finally(() => {
          inFlight = false
        })
    }, 1500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [importId, status])
  function select(next: CurriculumImport) {
    setCurrent(next)
    setRows(next.rows)
    setExcluded([])
    setRevertImpact(undefined)
    setHistory(before => [next, ...before.filter(item => item.id !== next.id)].slice(0, 20))
    setError(undefined)
  }
  async function run(action: () => Promise<CurriculumImport>) {
    setBusy(true)
    setError(undefined)
    try {
      select(await action())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '培养方案解析失败')
    } finally {
      setBusy(false)
    }
  }
  function parse(event: FormEvent) {
    event.preventDefault()
    const data = new FormData()
    if (file) data.append('file', file)
    else data.append('text', text.trim())
    if (route) data.append('processing_route', route)
    void run(() => api.createCurriculumImport(data))
  }
  async function confirm() {
    if (!current) return
    setBusy(true)
    setError(undefined)
    try {
      const result = await api.confirmCurriculumImport(current.id, selectedRows)
      select(result.import ?? { ...current, rows: selectedRows, status: 'confirmed' })
      onConfirmed()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程方案确认失败')
    } finally {
      setBusy(false)
    }
  }
  function update(key: string, values: Partial<CurriculumRow>) {
    setRows((before) => before.map((row) => (row.key === key ? { ...row, ...values } : row)))
  }
  async function prepareRevert() {
    if (!current) return
    setBusy(true); setError(undefined)
    try { setRevertImpact(await api.previewCurriculumRevert(current.id)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取撤销影响') }
    finally { setBusy(false) }
  }
  async function revert() {
    if (!current || !revertImpact) return
    setBusy(true); setError(undefined)
    try { select(await api.revertCurriculumImport(current.id)); onConfirmed() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '撤销失败'); setRevertImpact(undefined) }
    finally { setBusy(false) }
  }
  const selectedRows = rows.filter(row => !excluded.includes(row.key))
  const review = reviewCurriculum(selectedRows)
  const previous = history.filter(entry => entry.status === 'confirmed' && entry.id !== current?.id)
  const compared = previous.find(entry => entry.id === comparisonId) ?? previous[0]
  const comparison = compared ? compareCurriculum(selectedRows, compared.rows) : undefined
  const editable = status === 'preview'
  return (
    <ForestDialog title="导入培养方案" onClose={onClose} wide>
      <p className="forest-dialog-intro">
        导入 PDF、DOCX 或文本，先核对课程、学期与先修关系，再种入森林。
      </p>
      {error && (
        <p role="alert" className="forest-error">
          {error}
        </p>
      )}
      {!current ? (
        <>
          <form className="forest-import-form" onSubmit={parse}>
            <ProcessingRouteControl value={route} onChange={setRoute} disabled={busy} purpose="curriculum" />
            <label>
              培养方案文件
              <input
                type="file"
                accept=".pdf,.docx"
                onChange={(event) => {
                  setFile(event.target.files?.[0])
                  setError(undefined)
                }}
              />
            </label>
            {file && (
              <p>
                {file.name}{' '}
                <button type="button" onClick={() => setFile(undefined)}>
                  改用粘贴文本
                </button>
              </p>
            )}
            <label>
              粘贴培养方案
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={7}
                disabled={Boolean(file)}
                placeholder="粘贴课程名称、学期安排和原文明确的先修条件…"
              />
            </label>
            <button
              className="forest-action"
              type="submit"
              disabled={busy || (!file && !text.trim())}
            >
              {busy ? '正在登记…' : '解析并预览'}
            </button>
          </form>
          {history.length > 0 && (
            <details className="forest-import-history">
              <summary>最近导入记录</summary>
              {history.map((entry) => (
                <button type="button" key={entry.id} onClick={() => select(entry)}>
                  {entry.filename ?? '粘贴文本'}{' '}
                  <small>
                    {entry.status === 'reverted' ? '已撤销' : entry.status === 'confirmed'
                      ? '已确认'
                      : entry.status === 'preview'
                        ? '待核对'
                        : entry.status === 'failed'
                          ? '失败'
                          : '处理中'}
                  </small>
                </button>
              ))}
            </details>
          )}
        </>
      ) : (
        <>
          <div className="forest-import-heading">
            <strong>{current.filename ?? '粘贴文本培养方案'}</strong>
            <button
              type="button"
              onClick={() => {
                setCurrent(undefined)
                setRows([])
                setExcluded([])
                setRevertImpact(undefined)
              }}
              disabled={busy}
            >
              导入另一份
            </button>
          </div>
          {current.warnings.map((warning, index) => (
            <p className="forest-import-warning" key={index}>
              {warning}
            </p>
          ))}
          {current.mode && (
            <p className="forest-import-mode">
              提取方式：
              {current.mode.includes('local') || current.mode.includes('rule')
                ? '本地规则提取，请逐项核对'
                : current.mode === 'llm' ? '全程 AI 读页与提取' : '标准解析与 AI 提取'}
            </p>
          )}
          {(status === 'pending' || status === 'processing') && (
            <div role="status" className="forest-task-status">
              <span className="forest-loading-seed" aria-hidden="true">
                ❧
              </span>
              <h3>正在整理课程方案</h3>
              <progress value={current.progress ?? 0} max={100} aria-label="培养方案处理进度" />
              <p>{current.phase === 'reading' ? '正在逐页读取原文件。' : '正在分批整理课程。'}已完成步骤会保留，失败重试可继续处理。解析完成后进入预览，此时还没有创建课程。</p>
            </div>
          )}
          {status === 'failed' && (
            <div role="alert" className="forest-task-status">
              <p>{current.error_message ?? '解析任务失败，请检查输入后重试。'}</p>
              <button
                className="forest-action"
                type="button"
                disabled={busy}
                onClick={() => void run(() => api.retryCurriculumImport(current.id))}
              >
                重试解析
              </button>
            </div>
          )}
          {(status === 'preview' || status === 'confirmed' || status === 'reverted') && (
            <>
              <p className="forest-import-preview-hint">
                {status === 'reverted' ? '这次导入已撤销。新建的空课程已移入回收站，原有课程的属性已恢复。' : status === 'confirmed'
                  ? '课程方案已确认。原有课程和笔记已保留。'
                  : `${selectedRows.length} 门课程待核对。重复课程请选择已有课程进行关联。`}
              </p>
              <div className="forest-import-summary">
                <strong>已知学分合计 {review.credits}</strong>
                <span>{review.missingCredits ? `${review.missingCredits} 门未标学分，未计入合计` : '所选课程均已标注学分'}</span>
              </div>
              {editable && review.errors.map(message => <p role="alert" className="forest-import-warning" key={message}>{message}</p>)}
              {editable && excluded.length > 0 && <div className="forest-import-restores">
                <span>已排除 {excluded.length} 门：</span>
                {rows.filter(row => excluded.includes(row.key)).map(row => <button type="button" key={row.key} onClick={() => setExcluded(before => before.filter(key => key !== row.key))}>恢复 {row.name}</button>)}
              </div>}
              {editable && comparison && <details className="forest-import-comparison">
                <summary>与已确认方案对比：新增 {comparison.added.length} · 变化 {comparison.changed.length} · 本次未包含 {comparison.omitted.length}</summary>
                <label>对比方案<select value={compared.id} onChange={event => setComparisonId(event.target.value)}>{previous.map(entry => <option key={entry.id} value={entry.id}>{entry.filename ?? `粘贴文本 · ${entry.id.slice(0, 8)}`}</option>)}</select></label>
                {comparison.added.map(row => <p key={`added-${row.key}`}>新增：{row.name}</p>)}
                {comparison.changed.map(item => <p key={`changed-${item.row.key}`}>{item.row.name}：{item.fields.join('、')}变化</p>)}
                {comparison.omitted.map(row => <p key={`omitted-${row.key}`}>本次未包含：{row.name}（保留已有课程）</p>)}
              </details>}
              <div className="forest-import-table-wrap">
                <table className="forest-import-table">
                  <thead>
                    <tr>
                      <th>课程</th>
                      <th>学期</th>
                      <th>层级</th>
                      <th>先修课程</th>
                      <th>关联已有课程</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRows.map((row, index) => (
                      <tr key={row.key}>
                        <td>
                          <input
                            aria-label={`课程名称 ${index + 1}`}
                            value={row.name}
                            disabled={!editable}
                            onChange={(event) => update(row.key, { name: event.target.value })}
                            maxLength={200}
                          />
                          <details className="forest-import-metadata">
                            <summary>课程代码 · 学分 · 学时 · 必选修</summary>
                            <label>课程代码<input aria-label={`课程代码 ${index + 1}`} value={row.course_code ?? ''} maxLength={80} disabled={!editable} onChange={event => update(row.key, { course_code: event.target.value || null })} /></label>
                            {(['credits', 'hours'] as const).map(field => <label key={field}>{field === 'credits' ? '学分' : '学时'}<input aria-label={`${field === 'credits' ? '学分' : '学时'} ${index + 1}`} type="number" min={0} max={field === 'credits' ? 100 : 10000} step="any" value={row[field] ?? ''} disabled={!editable} onChange={event => update(row.key, { [field]: event.target.value === '' ? null : Number(event.target.value) })} /></label>)}
                            <label>必选修<select aria-label={`必选修 ${index + 1}`} value={row.requirement ?? 'unspecified'} disabled={!editable} onChange={event => update(row.key, { requirement: event.target.value as CurriculumRow['requirement'] })}><option value="unspecified">未注明</option><option value="required">必修</option><option value="elective">选修</option></select></label>
                          </details>
                          <details>
                            <summary>{row.source_label || '查看原文'}</summary>
                            <p>{row.source_excerpt}</p>
                          </details>
                          {status === 'preview' && (
                            <button
                              type="button"
                              className="forest-import-exclude"
                              aria-label={`不导入课程 ${index + 1}`}
                              onClick={() =>
                                setExcluded(before => [...before, row.key])
                              }
                            >
                              不导入此行
                            </button>
                          )}
                        </td>
                        <td>
                          <input
                            aria-label={`学期 ${index + 1}`}
                            type="number"
                            min="1"
                            max="30"
                            value={row.semester ?? ''}
                            disabled={!editable}
                            onChange={(event) =>
                              update(row.key, {
                                semester: event.target.value ? Number(event.target.value) : null,
                              })
                            }
                          />
                        </td>
                        <td>
                          <select
                            aria-label={`层级 ${index + 1}`}
                            value={row.level}
                            disabled={!editable}
                            onChange={(event) =>
                              update(row.key, { level: event.target.value as ForestLevel })
                            }
                          >
                            {Object.entries(levelLabels).map(([value, label]) => (
                              <option value={value} key={value}>
                                {label}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <input
                            aria-label={`先修课程 ${index + 1}`}
                            value={row.prerequisites.join('、')}
                            disabled={!editable}
                            placeholder="用逗号分隔"
                            onChange={(event) =>
                              update(row.key, {
                                prerequisites: event.target.value
                                  .split(/[,，、]/)
                                  .map((name) => name.trim())
                                  .filter(Boolean),
                              })
                            }
                          />
                        </td>
                        <td>
                          <select
                            aria-label={`关联已有课程 ${index + 1}`}
                            value={row.existing_course_id ?? ''}
                            disabled={!editable}
                            onChange={(event) =>
                              update(row.key, { existing_course_id: event.target.value || null,
                                expected_profile_revision: courses.find(course => course.course_id === event.target.value)?.revision ?? null })
                            }
                          >
                            <option value="">新建课程</option>
                            {courses.map((course) => (
                              <option value={course.course_id} key={course.course_id}>
                                {course.name}
                              </option>
                            ))}
                          </select>
                          {editable && row.existing_course_id && <small>将更新该课程的学期、层级与先修条件，保留笔记和学习状态。</small>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {status === 'preview' && (
                <footer className="forest-import-confirm">
                  <p>确认后创建新课程或关联已有课程，保留原有笔记与入口。</p>
                  <button
                    type="button"
                    className="forest-action"
                    disabled={busy || !selectedRows.length || review.errors.length > 0}
                    onClick={() => void confirm()}
                  >
                    {busy ? '正在确认…' : '确认课程方案'}
                  </button>
                </footer>
              )}
              {status === 'confirmed' && current.can_revert && !revertImpact && <footer className="forest-import-confirm">
                <p>仅在课程尚未被后续修改或使用时可撤销。撤销前会创建检查点。</p>
                <button type="button" disabled={busy} onClick={() => void prepareRevert()}>查看撤销影响</button>
              </footer>}
              {revertImpact && <section className="forest-import-comparison" aria-label="撤销影响">
                <h3>撤销这次课程方案</h3>
                {revertImpact.restore_courses.map(course => <p key={course.course_id}>恢复 {course.name}：学期 {course.semester ?? '未设置'}，{levelLabels[course.level]}，先修 {course.prerequisites.join('、') || '无'}</p>)}
                {revertImpact.recycle_courses.map(course => <p key={course.course_id}>移入回收站：{course.name}（新建且未使用）</p>)}
                <p>任何课程出现后续修改时，整次撤销都会被拒绝。</p>
                <div className="forest-import-restores"><button type="button" disabled={busy} onClick={() => setRevertImpact(undefined)}>保留课程方案</button><button type="button" disabled={busy} onClick={() => void revert()}>{busy ? '正在撤销…' : '确认撤销这次导入'}</button></div>
              </section>}
            </>
          )}
        </>
      )}
    </ForestDialog>
  )
}
