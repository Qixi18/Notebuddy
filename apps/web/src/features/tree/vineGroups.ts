import type { TreeRelation } from '../forest/types'
import type { Point } from './treeGeometry'

export type VineGroup = {
  id: string
  courses: [string, string]
  relations: TreeRelation[]
}

/** Display-only bundles. Every valid relation retains its real identity. */
export function groupForestVines(relations: TreeRelation[], endpoints: Map<string, Point>, noteBooks: Map<string, string> = new Map()): VineGroup[] {
  const pairs = new Map<string, Map<string, VineGroup>>()
  const seen = new Set<string>()
  for (const relation of [...relations].sort((a, b) => a.id.localeCompare(b.id))) {
    const sourceKnown = endpoints.has(relation.source_block_id) || noteBooks.has(relation.source_block_id)
    const targetKnown = endpoints.has(relation.target_block_id) || noteBooks.has(relation.target_block_id)
    if (seen.has(relation.id) || relation.status !== 'confirmed' || relation.stale || relation.source_course_id === relation.target_course_id || !sourceKnown || !targetKnown) continue
    seen.add(relation.id)
    const forward = relation.source_course_id.localeCompare(relation.target_course_id) < 0
    const courses: [string, string] = forward ? [relation.source_course_id, relation.target_course_id] : [relation.target_course_id, relation.source_course_id]
    const books = forward ? [noteBooks.get(relation.source_block_id), noteBooks.get(relation.target_block_id)] : [noteBooks.get(relation.target_block_id), noteBooks.get(relation.source_block_id)]
    const pairKey = JSON.stringify(courses)
    const key = JSON.stringify(books.map(book => book ?? 'course'))
    const buckets = pairs.get(pairKey) ?? new Map<string, VineGroup>()
    const group = buckets.get(key) ?? { id: `${pairKey}:${key}`, courses, relations: [] }
    group.relations.push(relation)
    buckets.set(key, group)
    pairs.set(pairKey, buckets)
  }
  return [...pairs].sort(([a], [b]) => a.localeCompare(b)).flatMap(([, buckets]) => {
    const ranked = [...buckets.values()].sort((a, b) => {
      const manual = (group: VineGroup) => group.relations.some(relation => relation.origin === 'manual') ? 1 : 0
      return manual(b) - manual(a) || b.relations.length - a.relations.length || a.id.localeCompare(b.id)
    })
    const visible = ranked.slice(0, 4).map(group => ({ ...group, relations: [...group.relations] }))
    for (const extra of ranked.slice(4)) {
      // Overflow is folded into the least crowded stem, never discarded.
      const destination = [...visible].sort((a, b) => a.relations.length - b.relations.length || a.id.localeCompare(b.id))[0]
      destination.relations.push(...extra.relations)
    }
    return visible.sort((a, b) => a.id.localeCompare(b.id)).map(group => ({ ...group, relations: group.relations.sort((a, b) => a.id.localeCompare(b.id)) }))
  })
}

export function visibleVineRelations(group: VineGroup, selectedId?: string, limit = 6) {
  const visible = group.relations.slice(0, limit)
  const selected = group.relations.find(relation => relation.id === selectedId)
  if (selected && !visible.includes(selected)) visible.splice(limit - 1, 1, selected)
  return visible
}
