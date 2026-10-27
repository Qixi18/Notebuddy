import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { TreeRelation } from '../forest/types'
import { ForestDialog } from '../forest/ForestDialog'
import type { Point } from './treeGeometry'
import type { CourseCanopy } from './courseCanopyGeometry'
import { pointAt } from './naturalBranchGeometry'
import { groupForestVines, type VineGroup } from './vineGroups'
import { VineLayer } from './VineLayer'
import type { VineExclusionZone, VineInput } from './vineGeometry'
import './vine.css'
import '../home/note-preview.css'

export type VineCourseGeometry = { x: number; y: number; canopy: CourseCanopy; scale?: number; grove?: number }
type Preview = { kind: 'relation' | 'group'; id: string; target: SVGGElement }

function branchAnchor(course: VineCourseGeometry, side: number, order: number, notebookId?: string): Point | undefined {
  const size = course.scale ?? 1
  const candidates = notebookId ? course.canopy.items.filter(item => item.book.id === notebookId) : course.canopy.items
  const item = [...candidates].sort((a, b) => side * (pointAt(b.branch.primary.curves, .6).x - pointAt(a.branch.primary.curves, .6).x))[0]
  // A notebook outside the overview connects to the shared course stock,
  // rather than borrowing an unrelated visible notebook's branch.
  if (!item) return notebookId ? { x: course.x - 8 * size, y: course.y - 180 * size } : undefined
  const local = pointAt(item.branch.primary.curves, [.70, .57, .48, .40][order])
  const scale = Number(item.transform?.match(/scale\(1,([^)]+)\)/)?.[1] ?? 1)
  const pivot = item.branch.primary.curves[0][0].y
  return { x: course.x + local.x * size, y: course.y + (pivot + (local.y - pivot) * scale) * size }
}

function GroupPreview({ preview, id, title, text, onEnter, onLeave }: { preview: Preview; id: string; title: string; text: string; onEnter: () => void; onLeave: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false })
  useLayoutEffect(() => {
    const measure = () => {
      const anchor = preview.target.getBoundingClientRect(), box = ref.current?.getBoundingClientRect()
      if (!box) return
      const top = anchor.top > box.height + 20 ? anchor.top - box.height - 12 : anchor.bottom + 12
      setPosition({ left: Math.max(box.width / 2 + 12, Math.min(innerWidth - box.width / 2 - 12, anchor.left + anchor.width / 2)), top: Math.max(12, Math.min(innerHeight - box.height - 12, top)), ready: true })
    }
    measure()
    window.addEventListener('resize', measure); window.addEventListener('scroll', measure, true)
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true) }
  }, [preview.target, title, text])
  return createPortal(<div ref={ref} role="tooltip" id={id} className="home-leaf-preview kt-vine-preview" style={{ left: position.left, top: position.top, visibility: position.ready ? 'visible' : 'hidden' }} onMouseEnter={onEnter} onMouseLeave={onLeave}><strong>{title}</strong><p>{text}</p><span className="home-leaf-preview-hint">{preview.kind === 'group' ? '点击藤茎，查看这组的全部联系' : '点击小叶子，查看依据与两端笔记'}</span></div>, document.body)
}

export function TreeVines({ relations, endpoints, selectedId, onRelation, zoom, noteBooks = new Map(), courseGeometry, viewKey, onSelectedPoint, stemHitRange, leafExclusions, layout = 'row' }: {
  relations: TreeRelation[]; endpoints: Map<string, Point>; noteBooks?: Map<string, string>
  selectedId?: string; onRelation: (relation: TreeRelation) => void; zoom: number
  courseGeometry?: Map<string, VineCourseGeometry>; viewKey?: string
  onSelectedPoint?: (relationId: string, point: Point) => void
  stemHitRange?: [number, number]
  leafExclusions?: VineExclusionZone[]
  layout?: 'row' | 'triangle' | 'grove'
}) {
  const groups = useMemo(() => groupForestVines(relations, endpoints, noteBooks), [relations, endpoints, noteBooks])
  const groupMap = useMemo(() => new Map(groups.map(group => [group.id, group])), [groups])
  const relationMap = useMemo(() => new Map(groups.flatMap(group => group.relations.map(relation => [relation.id, relation] as const))), [groups])
  const [openGroup, setOpenGroup] = useState<string>()
  const [preview, setPreview] = useState<Preview>()
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const keep = () => clearTimeout(timeout.current)
  const dismiss = () => { keep(); setPreview(undefined) }
  const leave = () => { keep(); timeout.current = setTimeout(() => setPreview(undefined), 180) }
  const previewId = `vine-preview-${useId().replace(/:/g, '')}`
  useEffect(() => () => clearTimeout(timeout.current), [])
  useEffect(() => { setPreview(undefined) }, [viewKey, zoom])
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') dismiss() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])
  const inputs = useMemo(() => {
    const counts = new Map<string, number>()
    const result: VineInput[] = []
    for (const group of groups) {
      const pair = JSON.stringify(group.courses), order = counts.get(pair) ?? 0
      counts.set(pair, order + 1)
      const selected = group.relations.find(relation => relation.id === selectedId)
      const representative = selected ?? group.relations.find(relation => endpoints.has(relation.source_block_id) && endpoints.has(relation.target_block_id)) ?? group.relations[0]
      let start = representative && endpoints.get(representative.source_block_id), end = representative && endpoints.get(representative.target_block_id)
      const a = courseGeometry?.get(group.courses[0]), b = courseGeometry?.get(group.courses[1])
      let midpoint: Point | undefined
      if (a && b) {
        const left = a.x <= b.x ? a : b, right = a.x <= b.x ? b : a
        const leftId = left === a ? group.courses[0] : group.courses[1]
        const rightId = right === a ? group.courses[0] : group.courses[1]
        const notebookFor = (courseId: string) => representative
          ? noteBooks.get(representative.source_course_id === courseId ? representative.source_block_id : representative.target_block_id)
          : undefined
        const between = [...courseGeometry!.values()].find(course => course.x > left.x + 30 && course.x < right.x - 30)
        // Long background vines across an intervening tree obscure its crown.
        // Explicitly selected relations remain available and are always drawn.
        const sameGrove = left.grove !== undefined && left.grove === right.grove
        if ((layout === 'row' || layout === 'grove' && !sameGrove) && !selected && between) continue
        if ((layout === 'triangle' || layout === 'grove' && sameGrove) && between && between.y < Math.min(left.y, right.y) - 30) midpoint = { x: between.x, y: between.y + 48 + order * 16 }
        start = branchAnchor(left, 1, order, notebookFor(leftId)) ?? start; end = branchAnchor(right, -1, order, notebookFor(rightId)) ?? end
      }
      if (!start || !end || Math.hypot(end.x - start.x, end.y - start.y) < 30) continue
      if (start.x > end.x) [start, end] = [end, start]
      result.push({ id: group.id, order, start, end, midpoint, relationIds: group.relations.map(relation => relation.id), leafRange: courseGeometry ? [.36,.64] : undefined, stemHitRange, startTangent: { x: 1, y: order === 0 ? -.5 : .2 }, endTangent: { x: 1, y: order === 0 ? .35 : -.3 } })
    }
    return result
  }, [groups, endpoints, noteBooks, selectedId, courseGeometry, stemHitRange, layout])
  const groupTitle = (group: VineGroup) => {
    const first = group.relations[0]
    return `${first.source_course_name ?? group.courses[0]}与${first.target_course_name ?? group.courses[1]}`
  }
  const relationTitle = (relation: TreeRelation) => `查看${relation.source_title}与${relation.target_title}的${relation.origin === 'ai' ? '模型推断关联' : '手动关联'}`
  const activate = (id: string) => { const relation = relationMap.get(id); if (relation) { dismiss(); setOpenGroup(undefined); onRelation(relation) } }
  const currentGroup = openGroup ? groupMap.get(openGroup) : undefined
  const previewRelation = preview?.kind === 'relation' ? relationMap.get(preview.id) : undefined
  const previewGroup = preview?.kind === 'group' ? groupMap.get(preview.id) : undefined
  return <g className="kt-vines">
    <VineLayer groups={inputs} screenScale={zoom} leafExclusions={leafExclusions} leafAtlasHref="/assets/forest/leaves-atlas.webp" selectedRelationId={selectedId} selectedGroupId={groups.find(group => group.relations.some(relation => relation.id === selectedId))?.id ?? openGroup} onSelectedPoint={onSelectedPoint}
      groupMembers={id => groupMap.get(id)!.relations.map(relation => relation.id).join('|')}
      groupLabel={id => `查看${groupTitle(groupMap.get(id)!)}的${groupMap.get(id)!.relations.length}条知识联系`}
      relationLabel={id => relationTitle(relationMap.get(id)!)} previewId={previewId} previewItemId={preview?.id}
      onPreview={item => { if (item) { keep(); setPreview(item) } else leave() }}
      onGroup={id => { dismiss(); setOpenGroup(id) }} onRelation={activate} />
    {preview && (previewRelation || previewGroup) && <GroupPreview id={previewId} preview={preview} onEnter={keep} onLeave={leave}
      title={previewRelation ? `${previewRelation.source_title} ↔ ${previewRelation.target_title}` : `${groupTitle(previewGroup!)}的知识联系`}
      text={previewRelation ? (previewRelation.reason.length > 130 ? `${previewRelation.reason.slice(0,130)}…` : previewRelation.reason) : `这根藤蔓承载 ${previewGroup!.relations.length} 条具体联系。缩小时会收起部分关系叶，完整联系保留在列表中。`} />}
    {currentGroup && createPortal(<ForestDialog title="藤蔓上的知识联系" onClose={() => setOpenGroup(undefined)}>
      <p className="kt-vine-group-heading">{groupTitle(currentGroup)} · {currentGroup.relations.length} 条联系</p>
      <div className="kt-vine-group-list">{currentGroup.relations.map(relation => <button key={relation.id} onClick={() => activate(relation.id)} className={relation.id === selectedId ? 'kt-vine-list-selected' : undefined}>
        <strong>{relation.source_title} <span aria-hidden="true">↔</span> {relation.target_title}</strong><small>{relation.origin === 'ai' ? '模型推断' : '手动关联'}</small><span>{relation.reason}</span>
      </button>)}</div>
    </ForestDialog>, document.body)}
  </g>
}
