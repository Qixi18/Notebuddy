type Section = { id: string; block_id?: string; material_id: string | null; notebook_id?: string | null }
type Outline<T extends Section> = {
  chapters: Array<{ id: string; sections: T[] }>
  historical_sections: T[]
  removed_chapters: Array<{ id: string; sections: T[] }>
}

export function resolveSection<T extends Section>(outline: Outline<T>, chapter?: string, section?: string): T | undefined {
  if (section) {
    const match = [...outline.chapters, ...outline.removed_chapters].flatMap((c) => c.sections)
      .concat(outline.historical_sections).find((s) => (s.block_id ?? s.id) === section)
    return match && (!chapter || chapter === (match.material_id ?? 'history')) ? match : undefined
  }
  if (chapter === 'history') return outline.historical_sections[0]
  if (chapter) return [...outline.chapters, ...outline.removed_chapters].find((c) => c.id === chapter)?.sections[0]
  return outline.chapters.flatMap((c) => c.sections)[0] ?? outline.historical_sections[0]
}

export function adjacentSection<T extends Section>(outline: Outline<T>, id: string, direction: 1 | -1): T | undefined {
  const sections = outline.chapters.flatMap((c) => c.sections).concat(outline.historical_sections)
  const index = sections.findIndex((s) => s.id === id)
  return index < 0 ? undefined : sections[index + direction]
}

export function notebookPath(courseId: string, section?: Section, mode?: string, notebookId = section?.notebook_id ?? undefined): string {
  const query = new URLSearchParams()
  if (section) {
    if (section.material_id) query.set('chapter', section.material_id)
    else if (!section.block_id) query.set('chapter', 'history')
    query.set('section', section.block_id ?? section.id)
  }
  if (mode === 'book') query.set('mode', 'book')
  return `/courses/${courseId}/${notebookId ? `notebooks/${notebookId}` : 'notebook'}${query.size ? `?${query}` : ''}`
}

export function shouldBlockNoteNavigation(dirty: boolean, current: { pathname: string; search: string }, next: { pathname: string; search: string }): boolean {
  // Notebook 内部切换目录项只改变 query 参数，编辑器会处理当前笔记内容；
  // 离开 Notebook 路由时才需要提示用户处理未保存草稿。
  const isNotebookPath = (pathname: string) => {
    const normalized = pathname.replace(/\/+$/, '') || '/'
    return /^\/courses\/[^/]+\/notebook$/i.test(normalized)
      || /^\/courses\/[^/]+\/notebooks\/[^/]+$/i.test(normalized)
      || /^\/notebooks\/unbound\/[^/]+$/i.test(normalized)
  }
  return dirty && isNotebookPath(current.pathname) && current.pathname !== next.pathname
}

export function mergeNotebookNotes<T extends { id: string; revision_number: number }>(current: T[], incoming: T[]): T[] {
  const merged = new Map(current.map((note) => [note.id, note]))
  for (const note of incoming) {
    if ((merged.get(note.id)?.revision_number ?? 0) <= note.revision_number) merged.set(note.id, note)
  }
  return [...merged.values()]
}
