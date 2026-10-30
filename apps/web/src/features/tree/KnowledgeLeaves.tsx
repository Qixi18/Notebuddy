import { useState } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import type { KnowledgeLeaf, NotebookGeometry } from './treeGeometry'
import type { LeafLabel } from './leafLabels'
import { LeafSprite } from './TreeSprites'
import { TreeAction } from './TreeAction'
import { sectionGrowthKey } from './growth/ledger'

export function KnowledgeLeaves({ labels, items, pins, growingNotes, zoom, search, onNote, onReveal }: {
  labels: LeafLabel[]; pins: Set<string>; growingNotes: Set<string>; zoom: number; search: string
  items: { branch: NotebookGeometry; leaves: KnowledgeLeaf[] }[]
  onNote: (book: NotebookRead, section: SectionRead) => void; onReveal: (leaf: KnowledgeLeaf) => void
}) {
  const [hovered, setHovered] = useState<string>()
  const textScale = Math.min(1, zoom)
  const labeled = new Set(labels.map(label => label.leaf.section.id))
  const unplaced = items.flatMap(({ branch, leaves }) => leaves.filter(leaf => !labeled.has(leaf.section.id)).map(leaf => ({ leaf, branch })))
  return <g className="kt-knowledge-leaves">{unplaced.map(({ leaf, branch }) => <g key={leaf.section.id} data-note-id={leaf.section.id} data-notebook-id={branch.book.id} data-growth-book={branch.book.id} data-growth-leaf={leaf.section.block_id ? sectionGrowthKey(branch.book.id, leaf.section.block_id) : undefined} className={leaf.section.block_id && growingNotes.has(sectionGrowthKey(branch.book.id, leaf.section.block_id)) ? 'kt-leaf-growth' : undefined}>
    <TreeAction label={`打开知识点：${leaf.section.title}`} onActivate={() => onNote(branch.book, leaf.section)} onFocus={() => onReveal(leaf)} className="kt-note kt-note-secondary">
      <title>{leaf.chapterTitle} · {leaf.section.title} · 完整目录在笔记本枝下</title>
      <g data-leaf-paint="true" className={hovered === leaf.section.id ? 'kt-physical-leaf-hover' : undefined} transform={`translate(${leaf.x},${leaf.y})`}><LeafSprite variant={leaf.variant} angle={leaf.angle} /></g>
      <circle cx={leaf.x} cy={leaf.y - 25} r="11" fill="transparent" className="kt-leaf-icon-hit" />
    </TreeAction>
  </g>)}{labels.map(({ leaf, branch, rect, showText }) => {
    const highlighted = pins.has(leaf.section.id) || Boolean(search && leaf.section.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
    const characters = Math.max(2, Math.min(12, Math.floor((rect.width * textScale - 8) / 13)))
    const text = leaf.section.title.length > characters ? `${leaf.section.title.slice(0, characters - 1)}…` : leaf.section.title
    const textX = branch.side < 0 ? rect.x + rect.width - 6 : rect.x + 6
    const baseline = rect.y + rect.height / 2 + 4 / textScale
    const edge = branch.side < 0 ? rect.x + rect.width : rect.x
    return <g key={leaf.section.id} data-note-id={leaf.section.id} data-notebook-id={branch.book.id} data-growth-book={branch.book.id} data-growth-leaf={leaf.section.block_id ? sectionGrowthKey(branch.book.id, leaf.section.block_id) : undefined} className={leaf.section.block_id && growingNotes.has(sectionGrowthKey(branch.book.id, leaf.section.block_id)) ? 'kt-leaf-growth' : undefined}>
      <path d={`M${leaf.x},${leaf.y - 25} Q${(leaf.x + edge) / 2},${leaf.y - 25} ${edge},${rect.y + rect.height / 2}`} fill="none" stroke="#8f9b71" strokeWidth=".7" opacity=".45" pointerEvents="none" aria-hidden="true" />
      <TreeAction label={`打开知识点：${leaf.section.title}`} onActivate={() => onNote(branch.book, leaf.section)} onFocus={() => onReveal({ ...leaf, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 + 25 })} className={`kt-note${highlighted ? ' kt-note-pinned' : ''}`}>
        <title>{leaf.chapterTitle} · {leaf.section.title}{leaf.section.user_locked ? ' · 已编辑' : ''}</title>
        <g data-leaf-paint="true" className={hovered === leaf.section.id ? 'kt-physical-leaf-hover' : undefined} transform={`translate(${leaf.x},${leaf.y})`}><LeafSprite variant={leaf.variant} angle={leaf.angle} /></g>
        <circle cx={leaf.x} cy={leaf.y - 25} r="11" fill="transparent" className="kt-leaf-icon-hit" />
        <rect {...rect} rx="6" fill="transparent" className="kt-leaf-hit" />
        {showText ? <>
          <rect {...rect} y={rect.y + (rect.height - 22 / textScale) / 2} height={22 / textScale} rx="3" fill="#e4edda" fillOpacity="1" pointerEvents="none" className="kt-note-label-bg" />
          <text x={textX} y={baseline} fontSize={13 / textScale} textAnchor={branch.side < 0 ? 'end' : 'start'} className="kt-note-label">{text}</text>
        </> : <circle cx={rect.x + rect.width / 2} cy={rect.y + rect.height / 2} r={3 / textScale} fill="#6f8650" stroke="#f7f5ea" strokeWidth={1 / textScale} pointerEvents="none" />}
      </TreeAction>
    </g>
  })}
    {/* Pointer targets follow the paint order above every proxy label. The
        original TreeActions remain the single keyboard/screen-reader entry. */}
    <g className="kt-leaf-pointer-layer" aria-hidden="true">
      {[...unplaced, ...labels].map(({ leaf, branch }) => <ellipse key={leaf.section.id} data-forest-interactive="true" data-leaf-hit-note-id={leaf.section.id} className="kt-leaf-pointer-hit"
        transform={`translate(${leaf.x},${leaf.y}) rotate(${leaf.angle})`} cx="0" cy="-30" rx="19" ry="31" fill="transparent" pointerEvents="all" cursor="pointer"
        onPointerEnter={() => setHovered(leaf.section.id)} onPointerLeave={() => setHovered(undefined)}
        onClick={event => { event.stopPropagation(); onNote(branch.book, leaf.section) }} />)}
    </g>
  </g>
}
