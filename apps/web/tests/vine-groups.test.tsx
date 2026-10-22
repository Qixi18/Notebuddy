import { expect, it } from 'vitest'
import { groupForestVines, visibleVineRelations } from '../src/features/tree/vineGroups'
import type { CrossCourseRelation } from '../src/features/forest/types'
import { buildVine, resolveVineLod } from '../src/features/tree/vineGeometry'

const relations = Array.from({ length: 35 }, (_, i) => ({ id: `r-${i}`, source_course_id: 'a', target_course_id: 'b', source_note_id: `a-${i}`, target_note_id: `b-${i}`, origin: 'ai', status: 'confirmed', stale: false } as CrossCourseRelation))
const endpoints = new Map(relations.flatMap((r, i) => [[r.source_note_id, { x: 100, y: i * 10 }], [r.target_note_id, { x: 800, y: i * 10 }]] as const))
const books = new Map(relations.flatMap((r, i) => [[r.source_note_id, `a-book-${i % 7}`], [r.target_note_id, `b-book-${i % 7}`]]))

it('retains every unique relation across no more than four stems, regardless of input order', () => {
  const groups = groupForestVines(relations, endpoints, books)
  expect(groups).toHaveLength(4)
  expect(groups.flatMap(group => group.relations.map(r => r.id)).sort()).toEqual(relations.map(r => r.id).sort())
  expect(groupForestVines([...relations].reverse(), endpoints, books)).toEqual(groups)
  expect(groupForestVines([...relations, relations[0]], endpoints, books)).toEqual(groups)
})

it('brings a selected relation into its limited leaf preview without losing it from the full group', () => {
  const group = groupForestVines(relations, endpoints)[0]
  expect(visibleVineRelations(group, 'r-9').map(r => r.id)).toContain('r-9')
  expect(visibleVineRelations(group, 'r-9')).toHaveLength(6)
  expect(group.relations).toHaveLength(35)
})

it('retains known off-preview notes in the bundle when only one pair of physical leaves is drawn', () => {
  const sparse = new Map([...endpoints].slice(0, 2))
  const groups = groupForestVines(relations, sparse, books)
  expect(groups.flatMap(group => group.relations)).toHaveLength(35)
})

it('thins a home relationship leaf hidden by a real knowledge sprig without dropping its group identity', () => {
  const vine = buildVine({ id: 'pair', order: 0, start: { x: 0, y: 200 }, end: { x: 700, y: 200 }, relationIds: ['r-0', 'r-1'] })
  const blocked = vine.leaves[0]
  const lod = resolveVineLod([vine], .8, blocked.relationId, [{ center: blocked.center, radius: 33 }])
  expect(lod.visible).not.toContain(blocked.relationId)
  expect(lod.hidden).toContain(blocked.relationId)
  expect(vine.leaves.map(leaf => leaf.relationId)).toEqual(['r-0', 'r-1'])
  expect(resolveVineLod([vine], .8, blocked.relationId).visible).toContain(blocked.relationId)
})
