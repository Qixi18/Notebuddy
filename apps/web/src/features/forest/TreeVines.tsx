import type { CrossCourseRelation } from './types'
import type { Point } from './treeGeometry'
import { TreeAction } from './TreeAction'
import { detailInteraction, operationSize } from './treeInteraction'

export function TreeVines({ relations, endpoints, selectedId, onRelation, zoom }: {
  relations: CrossCourseRelation[]; endpoints: Map<string, Point>
  selectedId?: string; onRelation: (relation: CrossCourseRelation) => void; zoom: number
}) {
  return <g className="kt-vines">{relations.filter(relation => relation.status === 'confirmed' && !relation.stale).map(relation => {
    const from = endpoints.get(relation.source_note_id), to = endpoints.get(relation.target_note_id)
    if (!from || !to) return null
    const lift = Math.min(150, Math.abs(to.x - from.x) * .16 + 48)
    const path = `M${from.x},${from.y} C${from.x + (to.x - from.x) * .3},${from.y - lift} ${from.x + (to.x - from.x) * .7},${to.y - lift} ${to.x},${to.y}`
    return <TreeAction disabled={!detailInteraction(zoom)} key={relation.id} label={`查看${relation.source_title}与${relation.target_title}的${relation.origin === 'ai' ? '模型推断关联' : '手动关联'}`} onActivate={() => onRelation(relation)} className={selectedId === relation.id ? 'kt-vine kt-vine-selected' : 'kt-vine'}>
      <title>{relation.reason} · {relation.origin === 'ai' ? '模型推断' : '手动关联'}</title>
      {detailInteraction(zoom) && <path d={path} fill="none" stroke="transparent" strokeWidth={operationSize(zoom)} />}
      <path d={path} fill="none" stroke="#66804b" strokeWidth="2.7" className="kt-vine-paint" />
      <path d={path} fill="none" stroke="#bac28a" strokeWidth=".9" transform="translate(0,-1)" pointerEvents="none" />
    </TreeAction>
  })}</g>
}
