import { useEffect, useRef } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import { notebookGeometry } from './treeGeometry'

export type TreeContentsSelection = { courseId: string; courseName: string; books: NotebookRead[]; notebookId?: string; trigger: Element | null }
export function TreeContents({ selection, onClose, onNotebook, onNote, onReveal }: {
  selection: TreeContentsSelection; onClose: () => void
  onNotebook: (courseId: string, notebookId: string) => void
  onNote: (courseId: string, notebookId: string, section: SectionRead) => void
  onReveal: (courseId: string, noteId: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.querySelector<HTMLElement>('button')?.focus() }, [])
  const books = selection.notebookId ? selection.books.filter(book => book.id === selection.notebookId) : selection.books
  return <div className="kt-contents" role="dialog" aria-modal="true" aria-label={`${selection.courseName}笔记目录`} ref={ref} onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); onClose() }
    if (event.key === 'Tab') {
      const buttons = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('button') ?? [])
      const first = buttons[0], last = buttons[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
  }}>
    <div className="kt-contents-heading"><h2>{selection.notebookId ? books[0]?.title : selection.courseName}</h2><button onClick={onClose} aria-label="关闭笔记目录">×</button></div>
    <p>每个知识点都保留自己的笔记入口。</p>
    <div className="kt-contents-scroll">{books.map(book => <section key={book.id}>
      <button className="kt-contents-book" onClick={() => onNotebook(selection.courseId, book.id)}>{book.title} · 继续阅读</button>
      {notebookGeometry(book).leaves.map(leaf => <div className="kt-contents-row" key={leaf.section.id}>
        <button onClick={() => onNote(selection.courseId, book.id, leaf.section)}>{leaf.chapterTitle} · {leaf.section.title}</button>
        <button aria-label={`在树上显露：${leaf.section.title}`} onClick={() => { onReveal(selection.courseId, leaf.section.id); onClose() }}>定位</button>
      </div>)}
      {!notebookGeometry(book).leaves.length && <p>还没有生成知识点，可从树根扩充这本笔记。</p>}
    </section>)}</div>
  </div>
}
