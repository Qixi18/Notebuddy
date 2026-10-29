import { useId, useMemo, useRef } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import type { CourseCanopy as CanopyGeometry } from './courseCanopyGeometry'
import type { KnowledgeLeaf } from './treeGeometry'
import { NaturalBranchWood } from './NaturalBranchWood'
import { TrunkSprite, RootstockSprite, LeafSprite } from './TreeSprites'
import { rootstockJoin } from './naturalBranchGeometry'
import { SaplingCrown } from './SaplingCrown'
import { TreeAction } from './TreeAction'
import { detailInteraction, operationSize } from './treeInteraction'
import { leafHitCells } from './leafHitCells'
import { sectionGrowthKey } from './growth/ledger'

export type LeafPreview = { book: NotebookRead; leaf: KnowledgeLeaf; target: SVGEllipseElement }

export function CourseCanopy({ canopy, empty, previewId, previewNoteId, onPreview, onLeave, onNotebook, onNote, zoom = 1, forest = false, growingBooks, growingNotes, highlighted }: {
  canopy: CanopyGeometry; empty: boolean; previewId: string; previewNoteId?: string; zoom?: number; forest?: boolean
  onPreview: (preview: LeafPreview) => void; onLeave: () => void
  onNotebook: (book: NotebookRead) => void; onNote: (book: NotebookRead, section: SectionRead) => void
  growingBooks?: Set<string>; growingNotes?: Set<string>
  highlighted?: Set<string>
}) {
  const texture = `canopy-wood-${useId().replace(/:/g, '')}`
  const targets = useRef(new Map<string, SVGEllipseElement>())
  const { items, variant } = canopy
  const books = [...new Map(items.map(item => [item.book.id, item.book])).values()]
  const hitCells = useMemo(() => forest ? leafHitCells(items.flatMap(item => item.leaves)) : new Map(), [items, forest])
  const clipIds = new Map([...hitCells.keys()].map((id, index) => [id, `${texture}-hit-${index}`]))
  const detail = !forest || detailInteraction(zoom)
  const barkCrop = ['200 796 64 160', '630 792 64 160', '1020 660 64 160'][variant]
  const show = (book: NotebookRead, leaf: KnowledgeLeaf) => {
    const target = targets.current.get(leaf.section.id)
    if (target) onPreview({ book, leaf, target })
  }
  return <>
    <defs>
      {[...hitCells].map(([id, cell]) => <clipPath key={id} id={clipIds.get(id)} clipPathUnits="userSpaceOnUse"><polygon points={cell.map((point: { x: number; y: number }) => `${point.x},${point.y}`).join(' ')} /></clipPath>)}
      <linearGradient id={`${texture}-wood`}><stop stopColor="#786c51" /><stop offset=".3" stopColor="#a18b65" /><stop offset=".58" stopColor="#c7b68a" /><stop offset="1" stopColor="#8c7b5d" /></linearGradient>
      <pattern id={`${texture}-bark`} patternUnits="userSpaceOnUse" width="36" height="90" x="-18" y="-45"><svg width="36" height="90" viewBox={barkCrop} preserveAspectRatio="none"><image href="/assets/forest/trunks-atlas.webp" width="1254" height="1254" /></svg></pattern>
      <linearGradient id={`${texture}-bark-feather`} x1="0" x2="0" y1="0" y2="1"><stop stopColor="black" /><stop offset=".2" stopColor="white" /><stop offset=".8" stopColor="white" /><stop offset="1" stopColor="black" /></linearGradient>
      <mask id={`${texture}-bark-edge`} maskContentUnits="objectBoundingBox"><rect width="1" height="1" fill={`url(#${texture}-bark-feather)`} /></mask>
      <linearGradient id={`${texture}-junction`} x1="0" x2="0" y1="-215" y2="-170" gradientUnits="userSpaceOnUse"><stop stopColor="black" /><stop offset="1" stopColor="white" /></linearGradient>
      <mask id={`${texture}-trunk`} maskUnits="userSpaceOnUse" x="-160" y="-280" width="320" height="330"><rect x="-160" y="-280" width="320" height="330" fill={`url(#${texture}-junction)`} /></mask>
    </defs>
    <ellipse cy="9" rx="180" ry="22" fill="#a2ab73" opacity=".14" aria-hidden="true" />
    {empty && <SaplingCrown variant={variant} textureId={texture} />}
    {items.map(({ branch, transform, scaleY }, index) => <g key={`${branch.book.id}-${index}`} transform={transform}>
      <g data-wood-notebook-id={branch.book.id} className={growingBooks?.has(branch.book.id) ? 'kt-branch-growth' : undefined}>
        <g data-trunk-join={branch.book.id}><NaturalBranchWood limb={rootstockJoin(branch.primary, scaleY)} textureId={texture} /></g>
        {branch.limbs.map(limb => <NaturalBranchWood key={limb.id} limb={limb} textureId={texture} />)}
      </g>
    </g>)}
    <g mask={!empty ? `url(#${texture}-trunk)` : undefined} pointerEvents="none" aria-hidden="true">{empty ? <TrunkSprite variant={variant} empty /> : <RootstockSprite variant={variant} />}</g>
    {books.map(book => <g className="kt-branch" key={book.id} data-notebook-id={book.id}>
      <TreeAction disabled={!detail} label={`续读笔记本：${book.title}`} className="kt-book-action" onActivate={() => onNotebook(book)}>
        <title>{book.title} · 打开笔记本</title>{items.filter(item => item.book.id === book.id).map((item, index) => <path key={index} transform={item.transform} d={item.branch.hitPath} fill="none" stroke="transparent" strokeWidth={forest ? operationSize(zoom) : 30} />)}
      </TreeAction>
    </g>)}
    {items.flatMap(({ book, leaves }) => leaves.map(leaf => <g key={leaf.section.id} data-note-id={leaf.section.id} data-notebook-id={book.id} data-growth-book={book.id} data-growth-leaf={leaf.section.block_id ? sectionGrowthKey(book.id, leaf.section.block_id) : undefined} className={leaf.section.block_id && growingNotes?.has(sectionGrowthKey(book.id, leaf.section.block_id)) ? 'kt-leaf-growth' : undefined} onMouseEnter={() => { if (detail) show(book, leaf) }} onMouseLeave={onLeave} onBlur={onLeave}>
      <TreeAction disabled={!detail} label={`打开知识点：${leaf.section.title}`} describedBy={previewNoteId === leaf.section.id ? previewId : undefined} className={`home-tree-leaf${forest ? ' kt-note' : ''}`} onActivate={() => onNote(book, leaf.section)} onFocus={() => show(book, leaf)}>
        <g data-leaf-paint="true" transform={`translate(${leaf.x},${leaf.y})`}>
          {[-62, 60].map((angle, index) => <g key={angle} transform={`rotate(${leaf.angle}) translate(0,3) rotate(${angle}) scale(.61) translate(0,-3)`}><LeafSprite variant={(leaf.variant + index + 1) % 4} /></g>)}
          <LeafSprite variant={previewNoteId === leaf.section.id || highlighted?.has(leaf.section.id) ? 4 : leaf.variant} angle={leaf.angle} />
        </g>
        <g clipPath={forest ? `url(#${clipIds.get(leaf.section.id)})` : undefined}>
        {[-62, 60].map(angle => <ellipse key={angle} transform={`translate(${leaf.x},${leaf.y}) rotate(${leaf.angle}) translate(0,3) rotate(${angle}) scale(.61) translate(0,-3)`} cx="0" cy="-30" rx="22" ry="33" fill="transparent" />)}
        <ellipse ref={element => { if (element) targets.current.set(leaf.section.id, element); else targets.current.delete(leaf.section.id) }} data-home-leaf-id={leaf.section.id} data-leaf-hit-note-id={forest ? leaf.section.id : undefined} transform={`translate(${leaf.x},${leaf.y}) rotate(${leaf.angle})`} cx="0" cy="-30" rx={forest ? Math.max(22, 22 / zoom) : 22} ry={forest ? Math.max(33, 22 / zoom) : 33} fill="transparent" />
        </g>
      </TreeAction>
    </g>))}
  </>
}
