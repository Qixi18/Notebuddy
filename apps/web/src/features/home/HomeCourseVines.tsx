import { useEffect, useState, type RefObject } from 'react'
import type { CourseTree } from '../../types'
import type { TreeRelation, ForestCourse } from '../forest/types'
import { courseCanopyGeometry } from '../tree/courseCanopyGeometry'
import { notebookGeometry, type Point } from '../tree/treeGeometry'
import { TreeVines, type VineCourseGeometry } from '../tree/TreeVines'
import type { VineExclusionZone } from '../tree/vineGeometry'

type Layout = { key: string; width: number; height: number; scale: number; courses: Map<string, VineCourseGeometry>; endpoints: Map<string, Point>; noteBooks: Map<string, string>; leafExclusions: VineExclusionZone[] }
const HOME_STEM_HIT_RANGE: [number, number] = [.32, .68]

/** Map independent xMidYMax tree SVGs into one non-zooming connection layer. */
export function HomeCourseVines({ host, courses, trees, selectedBooks, relations, selectedRelationId, onRelation }: {
  host: RefObject<HTMLDivElement | null>; courses: ForestCourse[]; trees: CourseTree[]; selectedBooks: Record<string, string>
  relations: TreeRelation[]; selectedRelationId?: string; onRelation: (relation: TreeRelation) => void
}) {
  const [layout, setLayout] = useState<Layout>()
  useEffect(() => {
    const root = host.current
    if (!root) return
    const measure = () => {
      const box = root.getBoundingClientRect()
      if (box.width <= 0 || box.height <= 0) return
      const crowns = courses.flatMap(course => {
        const article = [...root.querySelectorAll<HTMLElement>('[data-course-id]')].find(node => node.dataset.courseId === course.course_id)
        const svg = article?.querySelector<SVGSVGElement>('.home-course-tree')
        if (!svg) return []
        const rect = svg.getBoundingClientRect()
        const [x, y, width, height] = svg.getAttribute('viewBox')!.split(/\s+/).map(Number)
        if (!rect.width || !rect.height || !width || !height) return []
        const scale = Math.min(rect.width / width, rect.height / height)
        const books = [...(trees.find(tree => tree.course_id === course.course_id)?.notebooks ?? [])].filter(book => book.course_id === course.course_id).sort((a, b) => a.tree_slot - b.tree_slot)
        const canopy = courseCanopyGeometry(course.course_id, books, selectedBooks[course.course_id] ?? books[0]?.id)
        return [{ id: course.course_id, books, canopy, scale,
          x: rect.left - box.left + (rect.width - width * scale) / 2 - x * scale,
          y: rect.top - box.top + rect.height - height * scale - y * scale }]
      })
      const scale = crowns[0]?.scale ?? 1
      const geometry = new Map<string, VineCourseGeometry>(), endpoints = new Map<string, Point>(), noteBooks = new Map<string, string>()
      const leafExclusions: VineExclusionZone[] = []
      root.querySelectorAll('.home-course-card-header, .home-course-controls, .home-course-root').forEach(element => {
        const rect = element.getBoundingClientRect()
        if (rect.width > 0 && rect.height > 0) leafExclusions.push({ rect: { x: (rect.left - box.left) / scale, y: (rect.top - box.top) / scale, width: rect.width / scale, height: rect.height / scale } })
      })
      for (const crown of crowns) {
        geometry.set(crown.id, { x: crown.x / scale, y: crown.y / scale, scale: crown.scale / scale, canopy: crown.canopy })
        for (const item of crown.canopy.items) for (const leaf of item.leaves) {
          const angle = leaf.angle * Math.PI / 180
          const center = { x: (crown.x + (leaf.x + Math.sin(angle) * 30) * crown.scale) / scale, y: (crown.y + (leaf.y - Math.cos(angle) * 30) * crown.scale) / scale }
          endpoints.set(leaf.section.id, center)
          leafExclusions.push({ center, radius: 33 * crown.scale / scale })
          // The two side leaves use the exact same transforms as CourseCanopy.
          for (const side of [-62, 60]) {
            const turn = side * Math.PI / 180, x = Math.sin(turn) * 33 * .61, y = 3 - Math.cos(turn) * 33 * .61
            leafExclusions.push({ center: { x: (crown.x + (leaf.x + x * Math.cos(angle) - y * Math.sin(angle)) * crown.scale) / scale, y: (crown.y + (leaf.y + x * Math.sin(angle) + y * Math.cos(angle)) * crown.scale) / scale }, radius: 33 * .61 * crown.scale / scale })
          }
        }
        for (const book of crown.books) for (const leaf of notebookGeometry(book).leaves) noteBooks.set(leaf.section.id, book.id)
      }
      const key = JSON.stringify([box.width, box.height, crowns.map(crown => [crown.id, crown.x, crown.y, crown.scale, selectedBooks[crown.id], crown.canopy.items.map(item => item.leaves.map(leaf => leaf.section.id))]), [...noteBooks], leafExclusions])
      setLayout(previous => previous?.key === key ? previous : { key, width: box.width, height: box.height, scale, courses: geometry, endpoints, noteBooks, leafExclusions })
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure)
    observer?.observe(root)
    root.querySelectorAll('.home-course-tree').forEach(svg => observer?.observe(svg))
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure) }
  }, [host, courses, trees, selectedBooks])
  if (!layout || courses.length < 2) return null
  const visible = new Set(courses.map(course => course.course_id))
  return <svg className="home-vine-layer" width="100%" height="100%" viewBox={`0 0 ${layout.width} ${layout.height}`} aria-label="课程之间的知识藤蔓">
    <g transform={`scale(${layout.scale})`}><TreeVines relations={relations.filter(relation => visible.has(relation.source_course_id) && visible.has(relation.target_course_id))}
      courseGeometry={layout.courses} endpoints={layout.endpoints} noteBooks={layout.noteBooks} zoom={layout.scale} viewKey={layout.key} selectedId={selectedRelationId} onRelation={onRelation} stemHitRange={HOME_STEM_HIT_RANGE} leafExclusions={layout.leafExclusions} layout={courses.length === 3 ? 'triangle' : 'row'} /></g>
  </svg>
}
