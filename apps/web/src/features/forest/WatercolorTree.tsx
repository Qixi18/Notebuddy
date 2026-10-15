import { memo, useId, useMemo } from 'react'
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
import { projectNotebookControls } from './notebookControls'
import { NotebookWood } from './NotebookWood'

export const WatercolorTree = memo(function WatercolorTree({ tree, branches, zoom, pins, growingNotes, growingBooks, search, expandedBookId, onRoot, onNotebook, onNote, onExpand, onExpandBooks, onFocus, onReveal }: {
  tree: TreePosition; branches: NotebookGeometry[]; zoom: number; pins: Set<string>; growingNotes: Set<string>; search: string; expandedBookId?: string
  growingBooks?: Set<string>
  onRoot: () => void; onNotebook: (book: NotebookRead) => void; onNote: (book: NotebookRead, section: SectionRead) => void
  onExpand: (book: NotebookRead) => void; onExpandBooks: () => void; onFocus: () => void; onReveal: (leaf: KnowledgeLeaf) => void
}) {
  const id = `wood-${useId().replace(/:/g, '')}`
  const { course } = tree
  const visible = useMemo(() => overviewBranches(branches, pins, search), [branches, pins, search])
  const empty = branches.length === 0
  const detail = detailInteraction(zoom)
  const hitSize = detail ? operationSize(zoom) : 44
  const items = useMemo(() => visible.map(branch => ({ branch, leaves: overviewLeaves(branch, pins, search, expandedBookId === branch.book.id) })), [visible, pins, search, expandedBookId])
  const controls = projectNotebookControls(items, zoom)
  const labels = detail ? placeLeafLabels(items, zoom, controls) : []
  const crown = Math.min(-220, ...visible.map(branch => branch.origin.y))
  const trunkVariant = hashId(course.course_id) % 3
  // Opaque bark-only regions of the existing trunk atlas; not new raster assets.
  const barkCrop = ['200 796 64 160', '630 792 64 160', '1020 660 64 160'][trunkVariant]
  return <g transform={`translate(${tree.x},${tree.y})`} className={`kt-tree kt-tree-${course.learning_state}`} data-course-id={course.course_id}>
    <defs>
      <linearGradient id={`${id}-wood`} x1="0" y1="0" x2="1" y2=".4" gradientUnits="objectBoundingBox">
        <stop offset="0" stopColor="#776c54" /><stop offset=".3" stopColor="#a18e69" /><stop offset=".57" stopColor="#b3a17c" /><stop offset=".82" stopColor="#938163" /><stop offset="1" stopColor="#796e56" />
      </linearGradient>
      <pattern id={`${id}-bark`} patternUnits="userSpaceOnUse" width="44" height="110" x="-22" y="-55">
        <svg width="44" height="110" viewBox={barkCrop} preserveAspectRatio="none"><image href="/assets/forest/trunks-atlas.webp" width="1254" height="1254" /></svg>
      </pattern>
      <linearGradient id={`${id}-bark-feather`} x1="0" y1="0" x2="0" y2="1"><stop stopColor="black" /><stop offset=".16" stopColor="white" /><stop offset=".84" stopColor="white" /><stop offset="1" stopColor="black" /></linearGradient>
      <mask id={`${id}-bark-edge`} maskContentUnits="objectBoundingBox"><rect width="1" height="1" fill={`url(#${id}-bark-feather)`} /></mask>
      <linearGradient id={`${id}-crown-fade`} x1="0" x2="0" y1={crown - 24} y2={crown + 14} gradientUnits="userSpaceOnUse"><stop stopColor="black" /><stop offset="1" stopColor="white" /></linearGradient>
      <mask id={`${id}-trunk-junction`} maskUnits="userSpaceOnUse" x="-150" y="-600" width="300" height="650"><rect x="-150" y="-600" width="300" height="650" fill={`url(#${id}-crown-fade)`} /></mask>
    </defs>
    <g aria-hidden="true" pointerEvents="none">
      <ellipse cy="9" rx="182" ry="24" fill="#839063" opacity=".09" />
      <ellipse cx="-25" cy="14" rx="132" ry="14" fill="#b7be77" opacity=".12" />
      <path d="M-202 13Q-148-4-87 12T41 8T196 15" fill="none" stroke="#a6ad83" strokeWidth="1.2" opacity=".28" />
      <path d="M-119 14q-4-11-2-17m2 17q4-13 10-15M104 17q-2-13 2-21m-2 21q7-13 12-14M-68 21q-7-6-8-12m8 12q0-7 4-10" fill="none" stroke="#889365" strokeWidth="1.2" opacity=".48" />
      <path d="M-150 23q4-8 14-5l6 7q-11 4-20-2M130 27q4-8 13-6l5 6q-9 3-18 0" fill="#b7b5a2" stroke="#969981" strokeWidth=".6" opacity=".48" />
    </g>
    {items.map(({ branch, leaves }) => <NotebookWood key={branch.book.id} branch={branch} leaves={leaves} textureId={id} growing={growingBooks?.has(branch.book.id)} />)}
    <g aria-hidden="true" pointerEvents="none" mask={empty ? undefined : `url(#${id}-trunk-junction)`}><TrunkSprite variant={trunkVariant} empty={empty} /></g>
    {visible.map(branch => <NotebookBranch key={branch.book.id} branch={branch} controls={controls.get(branch.book.id)!} pins={pins} search={search} expanded={expandedBookId === branch.book.id} zoom={zoom} onNotebook={() => onNotebook(branch.book)} onExpand={() => onExpand(branch.book)} showDirectory={labels.some(label => label.branch.book.id === branch.book.id && !label.showText) || labels.filter(label => label.branch.book.id === branch.book.id).length < overviewLeaves(branch, pins, search, expandedBookId === branch.book.id).length} />)}
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
