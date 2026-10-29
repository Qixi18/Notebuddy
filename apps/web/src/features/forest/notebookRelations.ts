import type { CourseTree, SectionRead } from '../../types'
import type { NotebookRelation, TreeRelation } from './types'

/** Body block IDs are unique within a Notebook, not across the whole forest. */
export function sceneBlockId(notebookId: string, blockId: string): string {
  return JSON.stringify([notebookId, blockId])
}

export function projectDirectory(tree: CourseTree): CourseTree {
  return {
    ...tree,
    notebooks: tree.notebooks.map(book => {
      const section = (value: SectionRead): SectionRead[] => value.block_id
        ? [{ ...value, id: sceneBlockId(book.id, value.block_id) }]
        : []
      const chapters = (rows: typeof book.chapters) => rows.map(chapter => ({
        ...chapter, sections: chapter.sections.flatMap(section),
      }))
      return {
        ...book, chapters: chapters(book.chapters),
        historical_sections: book.historical_sections.flatMap(section),
        removed_chapters: chapters(book.removed_chapters ?? []),
      }
    }),
  }
}

/** A whole-Notebook link is drawn at its first current body section.
 * These are display anchors, not a claim that the section is source evidence.
 * Empty/missing books remain listed in the relation panel without a fake leaf.
 */
export function projectRelations(records: NotebookRelation[], trees: CourseTree[]): TreeRelation[] {
  const books = new Map(trees.flatMap(tree => tree.notebooks
    .filter(book => book.course_id === tree.course_id)
    .map(book => [book.id, book] as const)))
  return records.flatMap(record => {
    const source = books.get(record.source_notebook_id)
    const target = books.get(record.target_notebook_id)
    if (source?.course_id !== record.source_course_id || target?.course_id !== record.target_course_id) return []
    const anchor = (book: NonNullable<typeof source>, blockId?: string | null) => book.chapters
      .filter(chapter => !chapter.deleted_at).flatMap(chapter => chapter.sections)
      .concat(book.historical_sections).find(section => section.block_id && (!blockId || section.block_id === blockId))
    const sourceBlock = source && anchor(source, record.source_block_id)
    const targetBlock = target && anchor(target, record.target_block_id)
    if (!sourceBlock || !targetBlock) return []
    return [{
      ...record, source_block_id: sourceBlock.id, target_block_id: targetBlock.id,
      status: 'confirmed', stale: record.stale ?? false, origin: record.origin ?? 'manual',
    }]
  })
}
