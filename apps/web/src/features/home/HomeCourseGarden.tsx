import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import type { CourseTree, NotebookRead, SectionRead } from '../../types'
import type { TreeRelation, ForestCourse } from '../forest/types'
import { stateLabels } from '../forest/types'
import { notebookGeometry } from '../tree/treeGeometry'
import { HomeCourseTree, type HomeLeafPreview } from './HomeCourseTree'
import { HomeNotePreview } from './HomeNotePreview'
import { HomeCourseVines } from './HomeCourseVines'

type Actions = {
  onRoot: (courseId: string) => void
  onNotebook: (courseId: string, notebookId: string) => void
  onNote: (courseId: string, notebookId: string, section: SectionRead) => void
}
export function HomeCourseGarden({ courses, trees, relations = [], selectedRelationId, onRelation = () => {}, onVisibleCourseIdsChange, ...actions }: Actions & {
  courses: ForestCourse[]; trees: CourseTree[]; onVisibleCourseIdsChange?: (ids: string[]) => void
  relations?: TreeRelation[]; selectedRelationId?: string; onRelation?: (relation: TreeRelation) => void
}) {
  const grove = useRef<HTMLDivElement>(null)
  const [selectedBooks, setSelectedBooks] = useState<Record<string, string>>({})
  const visibleKey = courses.map(course => course.course_id).join('|')
  useEffect(() => { onVisibleCourseIdsChange?.(visibleKey ? visibleKey.split('|') : []) }, [visibleKey, onVisibleCourseIdsChange])
  return <div className="home-course-garden">
    <div className="home-garden-section-head"><div><span className="eyebrow">继续生长</span><h2>正在学的课程</h2></div><span className="home-course-count">{courses.length} 门课程</span></div>
    <div className="home-course-grove" ref={grove}>
    <div className={`home-course-grid${courses.length === 3 ? ' home-course-grid-triangle' : ''}`} style={{ '--home-columns': Math.max(1, courses.length) } as CSSProperties}>
      {courses.map(course => <HomeCourseCard key={course.course_id} course={course} directory={trees.find(tree => tree.course_id === course.course_id)} selected={selectedBooks[course.course_id]} onSelect={id => setSelectedBooks(previous => ({ ...previous, [course.course_id]: id }))} {...actions} />)}
    </div>
    <HomeCourseVines host={grove} courses={courses} trees={trees} selectedBooks={selectedBooks} relations={relations} selectedRelationId={selectedRelationId} onRelation={onRelation} />
    </div>
  </div>
}

function HomeCourseCard({ course, directory, selected, onSelect, onRoot, onNotebook, onNote }: Actions & { course: ForestCourse; directory?: CourseTree; selected?: string; onSelect: (id: string) => void }) {
  const books = useMemo(() => [...(directory?.notebooks ?? [])].filter(book => book.course_id === course.course_id).sort((a, b) => a.tree_slot - b.tree_slot), [directory, course.course_id])
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
    <div className="home-course-details">
    <header className="home-course-card-header"><h2 id={`home-course-${course.course_id}`}>{course.name}</h2><p><span className={`home-course-state home-course-state-${course.learning_state}`}><i />{stateLabels[course.learning_state]}</span><span>·</span>{books.length} 本笔记<span>·</span>{course.note_count} 个知识点</p></header>
    <section className="home-course-controls" aria-label={`${course.name}的笔记本入口`}>
      {activeBook ? <>
        <label className="home-book-picker"><select aria-label={`${course.name}的笔记本目录`} value={activeBook.id} onChange={event => { onSelect(event.target.value); dismissPreview() }}>{books.map(book => <option value={book.id} key={book.id}>{book.title}</option>)}</select></label>
        <button className="home-directory-more" aria-label={`打开${activeBook.title}的全部${leaves.length}个知识点`} onClick={() => openBook(activeBook)}>继续阅读 ↗</button>
      </> : <p className="home-course-empty" role={directory ? undefined : 'status'}>{directory ? '上传资料，让第一片知识叶子生长' : '正在读取课程目录…'}</p>}
    </section>
    <button className="home-course-root" aria-label={`课程菜单：${course.name}`} onClick={() => onRoot(course.course_id)}><span>＋</span> 添加资料与笔记本</button>
    </div>
    {preview && <HomeNotePreview id={previewId} preview={preview} courseId={course.course_id} onEnter={keepPreview} onLeave={leavePreview} onDismiss={dismissPreview} />}
  </article>
}
