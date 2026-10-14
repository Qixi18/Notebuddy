import { memo, useId } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import type { TreePosition } from './layout'
import { hashId } from './layout'
import { stateLabels } from './types'
import { overviewBranches, overviewLeaves, type NotebookGeometry, type KnowledgeLeaf } from './treeGeometry'
import { TrunkSprite } from './TreeSprites'
import { NotebookBranch } from './NotebookBranch'
import { TreeAction } from './TreeAction'
import { detailInteraction, operationSize } from './treeInteraction'
import { placeLeafLabels } from './leafLabels'
import { KnowledgeLeaves } from './KnowledgeLeaves'

export const WatercolorTree = memo(function WatercolorTree({ tree, branches, zoom, pins, growingNotes, search, expandedBookId, onRoot, onNotebook, onNote, onExpand, onExpandBooks, onFocus, onReveal }: {
  tree: TreePosition; branches: NotebookGeometry[]; zoom: number; pins: Set<string>; growingNotes: Set<string>; search: string; expandedBookId?: string
  onRoot: () => void; onNotebook: (book: NotebookRead) => void; onNote: (book: NotebookRead, section: SectionRead) => void
  onExpand: (book: NotebookRead) => void; onExpandBooks: () => void; onFocus: () => void; onReveal: (leaf: KnowledgeLeaf) => void
}) {
  const id = `wood-${useId().replace(/:/g, '')}`
  const { course } = tree
  const visible = overviewBranches(branches, pins, search)
  const empty = branches.length === 0
  const detail = detailInteraction(zoom)
  const hitSize = detail ? operationSize(zoom) : 44
  const items = visible.map(branch => ({ branch, leaves: overviewLeaves(branch, pins, search, expandedBookId === branch.book.id) }))
  const labels = detail ? placeLeafLabels(items, zoom) : []
  return <g transform={`translate(${tree.x},${tree.y})`} className={`kt-tree kt-tree-${course.learning_state}`} data-course-id={course.course_id}>
    <defs>
      <linearGradient id={`${id}-wood`} x1="0" y1="0" x2="1" y2=".4" gradientUnits="objectBoundingBox">
        <stop offset="0" stopColor="#75654d" /><stop offset=".27" stopColor="#ae9771" /><stop offset=".44" stopColor="#d2bb93" /><stop offset=".58" stopColor="#8b7657" /><stop offset=".79" stopColor="#c6b38d" /><stop offset="1" stopColor="#827257" />
      </linearGradient>
    </defs>
    <g aria-hidden="true" pointerEvents="none">
      <ellipse cy="9" rx="182" ry="24" fill="#839063" opacity=".09" />
      <ellipse cx="-25" cy="14" rx="132" ry="14" fill="#b7be77" opacity=".12" />
      <path d="M-202 13Q-148-4-87 12T41 8T196 15" fill="none" stroke="#a6ad83" strokeWidth="2" opacity=".4" />
      <TrunkSprite variant={hashId(course.course_id) % 3} empty={empty} />
    </g>
    {visible.map(branch => <NotebookBranch key={branch.book.id} branch={branch} pins={pins} search={search} expanded={expandedBookId === branch.book.id} zoom={zoom} textureId={id} onNotebook={() => onNotebook(branch.book)} onExpand={() => onExpand(branch.book)} showDirectory={labels.some(label => label.branch.book.id === branch.book.id && !label.showText) || labels.filter(label => label.branch.book.id === branch.book.id).length < overviewLeaves(branch, pins, search, expandedBookId === branch.book.id).length} />)}
    {detail && <KnowledgeLeaves labels={labels} items={items} pins={pins} growingNotes={growingNotes} zoom={zoom} search={search} onNote={onNote} onReveal={onReveal} />}
    <TreeAction disabled={!detail} label={`课程菜单：${course.name}`} onActivate={onRoot} onFocus={onFocus} className="kt-root">
      <title>{course.name} · 新建或扩充笔记本</title>
      <path d="M-116 15L-100-17Q-58-24 5-18T112-13L128 18Q89 37-6 31T-116 15Z" fill="#ece9db" stroke="#b8af97" strokeWidth="1.4" />
      <path d="M-113 17Q-6 33 127 18M-96-15Q-1-25 109-12" fill="none" stroke="#fcfbf4" strokeWidth="2" opacity=".8" />
      <rect x="-150" y="-100" width="300" height="145" rx="12" fill="transparent" />
      <text y="11" textAnchor="middle" className="kt-course-title">{course.name.length > 13 ? `${course.name.slice(0, 13)}…` : course.name}</text>
      <text y="58" textAnchor="middle" className="kt-state">{stateLabels[course.learning_state]}{empty ? ' · 从第一本笔记开始' : ` · ${branches.length} 本笔记`}</text>
    </TreeAction>
    {detail && branches.length > 6 && <TreeAction label={`展开${course.name}的全部${branches.length}本笔记本`} onActivate={onExpandBooks} transform="translate(0,86)" className="kt-aggregate">
      <rect x="-92" y="-20" width="184" height="44" rx="8" fill="#eae9d9" stroke="#b5b894" /><text y="7" textAnchor="middle">查看全部 {branches.length} 本笔记本</text>
      <rect x="-92" y={2 - hitSize / 2} width={Math.max(184, hitSize)} height={hitSize} fill="transparent" className="kt-aggregate-hit" />
    </TreeAction>}
  </g>
})
