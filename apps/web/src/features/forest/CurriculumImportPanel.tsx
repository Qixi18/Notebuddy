import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api'
import { ForestDialog } from './ForestDialog'
import {
  levelLabels,
  type CurriculumImport,
  type CurriculumRow,
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
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
    void run(() => api.createCurriculumImport(data))
  }
  async function confirm() {
    if (!current) return
    setBusy(true)
    setError(undefined)
    try {
      await api.confirmCurriculumImport(current.id, rows)
      setCurrent({ ...current, status: 'confirmed' })
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
                    {entry.status === 'confirmed'
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
                : current.mode}
            </p>
          )}
          {(status === 'pending' || status === 'processing') && (
            <div role="status" className="forest-task-status">
              <span className="forest-loading-seed" aria-hidden="true">
                ❧
              </span>
              <h3>正在整理课程方案</h3>
              <p>解析完成后会显示预览。此时还没有创建课程。</p>
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
          {(status === 'preview' || status === 'confirmed') && (
            <>
              <p className="forest-import-preview-hint">
                {status === 'confirmed'
                  ? '课程方案已确认。原有课程和笔记已保留。'
                  : `${rows.length} 门课程待核对。重复课程请选择已有课程进行关联。`}
              </p>
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
                    {rows.map((row, index) => (
                      <tr key={row.key}>
                        <td>
                          <input
                            aria-label={`课程名称 ${index + 1}`}
                            value={row.name}
                            disabled={status === 'confirmed'}
                            onChange={(event) => update(row.key, { name: event.target.value })}
                            maxLength={120}
                          />
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
                                setRows((current) => current.filter((item) => item.key !== row.key))
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
                            disabled={status === 'confirmed'}
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
                            disabled={status === 'confirmed'}
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
                            disabled={status === 'confirmed'}
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
                            disabled={status === 'confirmed'}
                            onChange={(event) =>
                              update(row.key, { existing_course_id: event.target.value || null })
                            }
                          >
                            <option value="">新建课程</option>
                            {courses.map((course) => (
                              <option value={course.course_id} key={course.course_id}>
                                {course.name}
                              </option>
                            ))}
                          </select>
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
                    disabled={busy || !rows.length || rows.some((row) => !row.name.trim())}
                    onClick={() => void confirm()}
                  >
                    {busy ? '正在确认…' : '确认课程方案'}
                  </button>
                </footer>
              )}
            </>
          )}
        </>
      )}
    </ForestDialog>
  )
}
