import { memo } from 'react'
import { TreeAction } from './TreeAction'
import { LeafSprite } from './TreeSprites'
import { overviewLeaves, type NotebookGeometry } from './treeGeometry'
import { detailInteraction, operationSize } from './treeInteraction'
import type { NotebookControls } from './notebookControls'

const short = (text: string, length: number) => text.length > length ? `${text.slice(0, length)}…` : text
export const NotebookBranch = memo(function NotebookBranch({ branch, controls, pins, search, expanded, zoom, onNotebook, onExpand, showDirectory = false }: {
  branch: NotebookGeometry; pins: Set<string>; search: string; expanded: boolean; zoom: number
  onNotebook: () => void; onExpand: () => void
  showDirectory?: boolean
  controls: NotebookControls
}) {
  const { side, book } = branch
  const leaves = overviewLeaves(branch, pins, search, expanded)
  const detail = detailInteraction(zoom)
  const hitSize = detail ? operationSize(zoom) : 44
  return <g className="kt-branch" data-notebook-id={book.id}>
    <TreeAction disabled={!detail} label={`续读笔记本：${book.title}`} onActivate={onNotebook} className="kt-book-action">
      <title>{book.title} · 继续上次阅读</title>
      <path d={branch.spine} stroke="transparent" strokeWidth={hitSize} fill="none" />
      <rect x={controls.title.x} y={controls.titleCenterY - 18} width="134" height="36" rx="3" fill="#f7f5ea" fillOpacity=".48" className="kt-book-plaque" />
      <rect {...controls.title} fill="transparent" className="kt-book-hit" />
      <text x={side < 0 ? controls.title.x + controls.title.width - 16 : controls.title.x + 28} y={controls.titleCenterY + 4} textAnchor={side < 0 ? 'end' : 'start'} className="kt-book-title">{short(book.title, 9)}</text>
    </TreeAction>
    {!detail && leaves.map(leaf => <g key={leaf.section.id} transform={`translate(${leaf.x},${leaf.y})`} pointerEvents="none" aria-hidden="true"><LeafSprite variant={leaf.variant} angle={leaf.angle} /></g>)}
    {detail && (branch.leaves.length > 6 || showDirectory) && <TreeAction label={`展开${book.title}的全部${branch.leaves.length}个知识点`} onActivate={onExpand} className="kt-aggregate" transform={`translate(${controls.directoryTranslate.x},${controls.directoryTranslate.y})`}>
      <rect x={side < 0 ? -128 : -8} y="-6" width="136" height="44" rx="8" fill="#eae9d9" stroke="#b5b894" />
      <rect x={side < 0 ? -128 : -8} y={16 - hitSize / 2} width={Math.max(136, hitSize)} height={hitSize} fill="transparent" className="kt-aggregate-hit" />
      <text x={side < 0 ? -60 : 60} y="21" textAnchor="middle">{showDirectory ? '目录' : '展开'} {branch.leaves.length} 个知识点</text>
    </TreeAction>}
  </g>
})
