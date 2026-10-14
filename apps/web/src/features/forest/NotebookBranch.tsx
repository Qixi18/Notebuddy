import { memo } from 'react'
import type { SectionRead } from '../../types'
import { TreeAction } from './TreeAction'
import { LeafSprite } from './TreeSprites'
import { overviewLeaves, type NotebookGeometry, type KnowledgeLeaf } from './treeGeometry'

const short = (text: string, length: number) => text.length > length ? `${text.slice(0, length)}…` : text
export const NotebookBranch = memo(function NotebookBranch({ branch, pins, growingNotes, search, expanded, zoom, textureId, onNotebook, onNote, onExpand, onReveal }: {
  branch: NotebookGeometry; pins: Set<string>; growingNotes: Set<string>; search: string; expanded: boolean; zoom: number; textureId: string
  onNotebook: () => void; onNote: (section: SectionRead) => void; onExpand: () => void; onReveal: (leaf: KnowledgeLeaf) => void
}) {
  const { origin: o, anchor: a, side, book } = branch
  const leaves = overviewLeaves(branch, pins, search, expanded)
  const tip = { x: a.x + side * 29, y: a.y - 151 }
  const taper = `M${o.x - 13},${o.y + 3} C${side * 42 - 9},${o.y - 22} ${a.x - side * 35},${a.y + 58} ${a.x - 3},${a.y} Q${a.x + side * 16},${a.y - 96} ${tip.x},${tip.y} Q${a.x + side * 16 + 4},${a.y - 96} ${a.x + 4},${a.y} C${a.x - side * 15},${a.y + 61} ${side * 52 + 9},${o.y - 12} ${o.x + 13},${o.y + 5}Z`
  return <g className="kt-branch" data-notebook-id={book.id}>
    <g aria-hidden="true" pointerEvents="none">
      <path d={taper} fill={`url(#${textureId}-wood)`} stroke="#78674f" strokeWidth=".7" />
      <path d={branch.spine} fill="none" stroke="#c1af88" strokeWidth="3.8" opacity=".8" />
      <path d={branch.spine} fill="none" stroke="#6e604a" strokeWidth="1.1" strokeDasharray="17 7 4 9" opacity=".65" />
      <path d={branch.spine} fill="none" stroke="#f0dfb5" strokeWidth=".9" transform={`translate(${side * 2},0)`} opacity=".65" />
      {leaves.map(leaf => <path key={leaf.section.id} d={`M${a.x},${a.y} Q${leaf.stem.x + side * 9},${leaf.stem.y + 24} ${leaf.stem.x},${leaf.stem.y} Q${leaf.x - 9},${leaf.y + 9} ${leaf.x},${leaf.y + 3}`} fill="none" stroke="#8b7657" strokeWidth="1.7" />)}
    </g>
    <TreeAction label={`续读笔记本：${book.title}`} onActivate={onNotebook} className="kt-book-action">
      <title>{book.title} · 继续上次阅读</title>
      <path d={branch.spine} stroke="transparent" strokeWidth={zoom >= .35 ? 44 / Math.min(1, zoom) : 44} fill="none" />
      <rect x={a.x + (side < 0 ? -112 : -22)} y={a.y + 17} width="134" height="44" rx="8" fill="#f7f5ea" fillOpacity=".88" className="kt-book-plaque" />
      <text x={a.x + side * 6} y={a.y + 43} textAnchor={side < 0 ? 'end' : 'start'} className="kt-book-title">{short(book.title, 9)}</text>
    </TreeAction>
    {leaves.map(leaf => {
      const highlighted = pins.has(leaf.section.id) || Boolean(search && leaf.section.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
      const labelX = leaf.x + side * 37
      return <g key={leaf.section.id} className={growingNotes.has(leaf.section.id) ? 'kt-leaf-growth' : undefined}>
        <TreeAction label={`打开知识点：${leaf.section.title}`} onActivate={() => onNote(leaf.section)} onFocus={() => onReveal(leaf)} className={`kt-note${highlighted ? ' kt-note-pinned' : ''}`}>
          <title>{leaf.chapterTitle} · {leaf.section.title}{leaf.section.user_locked ? ' · 已编辑' : ''}</title>
          <g transform={`translate(${leaf.x},${leaf.y})`}><LeafSprite variant={leaf.variant} angle={leaf.angle} /></g>
          <rect x={leaf.x - Math.max(32, 22 / Math.max(.35, zoom))} y={leaf.y - 70} width={Math.max(64, 44 / Math.max(.35, zoom))} height={Math.max(76, 44 / Math.max(.35, zoom))} rx="18" fill="transparent" className="kt-leaf-hit" />
          {(zoom >= .58 || highlighted) && <>
            <rect x={side < 0 ? labelX - 110 : labelX - 3} y={leaf.y - 53} width="114" height="44" rx="6" fill="#f7f5ea" fillOpacity=".82" className="kt-note-label-bg" />
            <text x={labelX} y={leaf.y - 26} textAnchor={side < 0 ? 'end' : 'start'} className="kt-note-label">{short(leaf.section.title, 8)}</text>
          </>}
        </TreeAction>
      </g>
    })}
    {branch.leaves.length > 6 && <TreeAction label={`展开${book.title}的全部${branch.leaves.length}个知识点`} onActivate={onExpand} className="kt-aggregate" transform={`translate(${a.x + side * 16},${a.y + 66})`}>
      <rect x={side < 0 ? -128 : -8} y="-6" width="136" height="44" rx="8" fill="#eae9d9" stroke="#b5b894" />
      <text x={side < 0 ? -60 : 60} y="21" textAnchor="middle">展开 {branch.leaves.length} 个知识点</text>
    </TreeAction>}
  </g>
})
