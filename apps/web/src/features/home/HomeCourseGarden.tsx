import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import type { CourseTree, NotebookRead, SectionRead } from '../../types'
import type { ForestCourse } from '../forest/types'
import { stateLabels } from '../forest/types'
import { notebookGeometry } from '../tree/treeGeometry'
import { HomeCourseTree, type HomeLeafPreview } from './HomeCourseTree'
import { HomeNotePreview } from './HomeNotePreview'

type Actions = {
  onRoot: (courseId: string) => void
  onNotebook: (courseId: string, notebookId: string) => void
  onNote: (courseId: string, notebookId: string, section: SectionRead) => void
}
export function HomeCourseGarden({ courses, trees, onVisibleCourseIdsChange, ...actions }: Actions & {
  courses: ForestCourse[]; trees: CourseTree[]; onVisibleCourseIdsChange?: (ids: string[]) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState(2)
  const [page, setPage] = useState(0)
  useEffect(() => {
    const measure = () => {
      const width = host.current?.getBoundingClientRect().width ?? 0
      if (width > 0) setSize(width >= 1440 ? 3 : width >= 640 ? 2 : 1)
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure)
    if (host.current) observer?.observe(host.current)
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  const pages = Math.max(1, Math.ceil(courses.length / size))
  const current = Math.min(page, pages - 1)
  const visible = courses.slice(current * size, (current + 1) * size)
  const visibleKey = visible.map(course => course.course_id).join('|')
  useEffect(() => { onVisibleCourseIdsChange?.(visibleKey ? visibleKey.split('|') : []) }, [visibleKey, onVisibleCourseIdsChange])
  return <div className="home-course-garden" ref={host}>
    <div className="home-garden-section-head"><div><span className="eyebrow">继续生长</span><h2>最近的课程</h2></div><div className="home-course-pagination">
      <span>{courses.length} 门课程{pages > 1 ? ` · ${current + 1} / ${pages}` : ''}</span>
      {pages > 1 && <><button aria-label="上一组课程" disabled={current === 0} onClick={() => setPage(current - 1)}>←</button><button aria-label="下一组课程" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>→</button></>}
    </div></div>
    <div className="home-course-grid" style={{ '--home-columns': Math.min(size, Math.max(1, visible.length)) } as CSSProperties}>
      {visible.map(course => <HomeCourseCard key={course.course_id} course={course} directory={trees.find(tree => tree.course_id === course.course_id)} {...actions} />)}
    </div>
  </div>
}

function HomeCourseCard({ course, directory, onRoot, onNotebook, onNote }: Actions & { course: ForestCourse; directory?: CourseTree }) {
  const books = useMemo(() => [...(directory?.notebooks ?? [])].filter(book => book.course_id === course.course_id).sort((a, b) => a.tree_slot - b.tree_slot), [directory, course.course_id])
  const [selected, setSelected] = useState<string>()
  const [preview, setPreview] = useState<HomeLeafPreview>()
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const keepPreview = () => { clearTimeout(hideTimer.current) }
  const dismissPreview = () => { keepPreview(); setPreview(undefined) }
  const leavePreview = () => { keepPreview(); hideTimer.current = setTimeout(() => setPreview(undefined), 180) }
  useEffect(() => () => clearTimeout(hideTimer.current), [])
  const showPreview = (next: HomeLeafPreview) => {
    keepPreview()
    setPreview(next)
  }
  const activeBook: NotebookRead | undefined = books.find(book => book.id === selected) ?? books[0]
  const leaves = activeBook ? notebookGeometry(activeBook).leaves : []
  const openBook = (book: NotebookRead) => onNotebook(course.course_id, book.id)
  const previewId = `home-preview-${course.course_id}`
  return <article className={`home-course-card kt-tree-${course.learning_state}`} data-course-id={course.course_id} aria-labelledby={`home-course-${course.course_id}`}>
    <HomeCourseTree courseId={course.course_id} books={books} selectedBookId={activeBook?.id} previewId={previewId} previewNoteId={preview?.leaf.section.id} onPreview={showPreview} onLeave={leavePreview} onNotebook={openBook} onNote={(book, section) => onNote(course.course_id, book.id, section)} />
    <header className="home-course-card-header"><h2 id={`home-course-${course.course_id}`}>{course.name}</h2><p><span className={`home-course-state home-course-state-${course.learning_state}`}><i />{stateLabels[course.learning_state]}</span><span>·</span>{books.length} 本笔记<span>·</span>{course.note_count} 个知识点</p></header>
    <section className="home-course-controls" aria-label={`${course.name}的笔记本入口`}>
      {activeBook ? <>
        <label className="home-book-picker"><select aria-label={`${course.name}的笔记本目录`} value={activeBook.id} onChange={event => { setSelected(event.target.value); dismissPreview() }}>{books.map(book => <option value={book.id} key={book.id}>{book.title}</option>)}</select></label>
        <button className="home-directory-more" aria-label={`打开${activeBook.title}的全部${leaves.length}个知识点`} onClick={() => openBook(activeBook)}>继续阅读 ↗</button>
      </> : <p className="home-course-empty" role={directory ? undefined : 'status'}>{directory ? '上传资料，让第一片知识叶子生长' : '正在读取课程目录…'}</p>}
    </section>
    <button className="home-course-root" aria-label={`课程菜单：${course.name}`} onClick={() => onRoot(course.course_id)}><span>＋</span> 添加资料与笔记本</button>
    {preview && <HomeNotePreview id={previewId} preview={preview} courseId={course.course_id} onEnter={keepPreview} onLeave={leavePreview} onDismiss={dismissPreview} />}
  </article>
}
