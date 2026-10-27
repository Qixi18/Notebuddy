import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api'
import { EmptyState } from '../components/EmptyState'
import { useWorkspace } from '../components/AppLayout'

type SectionRow = {
  block_id: string
  heading: string
  level: number
  order: number
  excerpt: string
}

type NotebookStructure = {
  notebook_id: string
  title: string
  revision: number
  sections: SectionRow[]
}

export function CourseKnowledgeStructure() {
  const { courseId = '' } = useParams()
  const { course } = useWorkspace()
  const [notebooks, setNotebooks] = useState<NotebookStructure[]>([])
  const [query, setQuery] = useState('')
  const [notebookId, setNotebookId] = useState('')
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    setNotebookId('')
    void api.getKnowledgeStructure(courseId).then((value) => {
      if (!active) return
      setNotebooks(value.notebooks)
      setError(undefined)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : '知识结构读取失败')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [courseId])

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    const selected = notebooks.filter(book => !notebookId || book.notebook_id === notebookId)
    if (!needle) return selected
    return selected.map((book) => ({
      ...book,
      sections: book.sections.filter((section) => `${section.heading} ${section.excerpt}`.toLocaleLowerCase().includes(needle)),
    })).filter((book) => book.sections.length > 0)
  }, [notebooks, query, notebookId])

  if (loading) return <div className="page-loading" role="status">正在读取知识结构…</div>
  if (error) return <p className="form-error" role="alert">{error}</p>

  return (
    <div className="course-knowledge-structure">
      <div className="section-heading-row">
        <div>
          <span className="eyebrow">{course?.name ?? '当前课程'}</span>
          <h2>知识结构</h2>
          <p>在笔记章节中查找知识，正文修改后这里同步更新。</p>
        </div>
        <label>筛选笔记本<select value={notebookId} onChange={event => setNotebookId(event.target.value)}>
          <option value="">全部笔记本</option>
          {notebooks.map(book => <option key={book.notebook_id} value={book.notebook_id}>{book.title}</option>)}
        </select></label>
        <label className="course-notes-search">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索小节标题或正文" aria-label="搜索知识结构" />
        </label>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon="⌘" title="还没有可展示的结构" description="先在笔记本中生成或编辑正文，章节会自动出现在这里。" />
      ) : filtered.map((book) => (
        <section className="tree-lecture-group" key={book.notebook_id} aria-label={book.title}>
          <div className="tree-lecture">
            <strong>{book.title}</strong>
            <small>{book.sections.length} 个小节</small>
          </div>
          <div className="tree-node-children">
            {book.sections.map((section) => (
              <Link
                className="tree-node"
                key={section.block_id}
                to={`/courses/${courseId}/notebooks/${book.notebook_id}?section=${encodeURIComponent(section.block_id)}`}
              >
                <span className="tree-node-name">{section.heading || `第 ${section.order + 1} 节`}</span>
                <small>{section.excerpt ? `${section.excerpt.slice(0, 120)}${section.excerpt.length > 120 ? '…' : ''}` : '打开正文'}</small>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
