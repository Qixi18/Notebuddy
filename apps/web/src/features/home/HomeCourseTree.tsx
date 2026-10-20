import { useId, useMemo, useRef } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import { hashId } from '../tree/layout'
import { notebookGeometry, type KnowledgeLeaf } from '../tree/treeGeometry'
import { buildTree } from '../tree/naturalBranchGeometry'
import { NaturalBranchWood } from '../tree/NaturalBranchWood'
import { TrunkSprite, LeafSprite } from '../tree/TreeSprites'
import { SaplingCrown } from '../tree/SaplingCrown'
import { TreeAction } from '../tree/TreeAction'
import '../tree/knowledge-tree.css'

export function homePreviewBooks(books: NotebookRead[], selectedBookId?: string) {
  const preview = books.slice(0, 3)
  const selected = books.find(book => book.id === selectedBookId)
  if (selected && !preview.includes(selected)) preview.splice(2, 1, selected)
  return preview
}
export type HomeLeafPreview = { book: NotebookRead; leaf: KnowledgeLeaf; target: SVGEllipseElement }

export function HomeCourseTree({ courseId, books, selectedBookId, previewId, previewNoteId, onPreview, onLeave, onNotebook, onNote }: {
  courseId: string; books: NotebookRead[]; selectedBookId?: string; previewId: string; previewNoteId?: string
  onPreview: (preview: HomeLeafPreview) => void; onLeave: () => void
  onNotebook: (book: NotebookRead) => void; onNote: (book: NotebookRead, section: SectionRead) => void
}) {
  const texture = `home-wood-${useId().replace(/:/g, '')}`
  const targets = useRef(new Map<string, SVGEllipseElement>())
  const variant = hashId(courseId) % 3 as 0 | 1 | 2
  const { geometry, items } = useMemo(() => {
    const preview = homePreviewBooks(books, selectedBookId)
    const originals = preview.map(book => notebookGeometry(book).leaves.slice(0, 6))
    const geometry = buildTree({ id: courseId, variant, books: preview.map((book, index) => ({ id: book.id, title: book.title, treeSlot: index, notes: originals[index].map((leaf, slot) => ({ id: leaf.section.id, title: leaf.section.title, treeSlot: slot })) })) })
    const items = geometry.books.map((branch, index) => ({ book: preview[index], branch, leaves: branch.leaves.map((leaf, slot) => ({ ...originals[index][slot], x: leaf.anchor.x, y: leaf.anchor.y, stem: leaf.petiole, angle: leaf.angle, variant: [0, 1, 2, 1, 0, 3][leaf.variant] })) }))
    return { geometry, items }
  }, [books, courseId, selectedBookId, variant])
  const bounds = books.length ? geometry.bounds : { x: -270, y: -510, width: 540, height: 550 }
  const barkCrop = ['200 796 64 160', '630 792 64 160', '1020 660 64 160'][variant]
  const show = (book: NotebookRead, leaf: KnowledgeLeaf) => {
    const target = targets.current.get(leaf.section.id)
    if (target) onPreview({ book, leaf, target })
  }
  return <svg className="home-course-tree" viewBox={`${bounds.x - 18} ${bounds.y - 8} ${bounds.width + 36} ${bounds.height + 16}`} preserveAspectRatio="xMidYMax meet" aria-label="课程知识树，枝干打开笔记本，叶子打开知识点">
    <defs>
      <linearGradient id={`${texture}-wood`}><stop stopColor="#786c51" /><stop offset=".3" stopColor="#a18b65" /><stop offset=".58" stopColor="#c7b68a" /><stop offset="1" stopColor="#8c7b5d" /></linearGradient>
      <pattern id={`${texture}-bark`} patternUnits="userSpaceOnUse" width="36" height="90" x="-18" y="-45"><svg width="36" height="90" viewBox={barkCrop} preserveAspectRatio="none"><image href="/assets/forest/trunks-atlas.webp" width="1254" height="1254" /></svg></pattern>
      <linearGradient id={`${texture}-bark-feather`} x1="0" x2="0" y1="0" y2="1"><stop stopColor="black" /><stop offset=".2" stopColor="white" /><stop offset=".8" stopColor="white" /><stop offset="1" stopColor="black" /></linearGradient>
      <mask id={`${texture}-bark-edge`} maskContentUnits="objectBoundingBox"><rect width="1" height="1" fill={`url(#${texture}-bark-feather)`} /></mask>
      <linearGradient id={`${texture}-junction`} x1="0" x2="0" y1="-305" y2="-245" gradientUnits="userSpaceOnUse"><stop stopColor="black" /><stop offset="1" stopColor="white" /></linearGradient>
      <mask id={`${texture}-trunk`} maskUnits="userSpaceOnUse" x="-150" y="-600" width="300" height="650"><rect x="-150" y="-600" width="300" height="650" fill={`url(#${texture}-junction)`} /></mask>
    </defs>
    <ellipse cy="9" rx="180" ry="22" fill="#a2ab73" opacity=".14" aria-hidden="true" />
    {books.length === 0 && <SaplingCrown variant={variant} textureId={texture} />}
    {items.map(({ branch }) => <g key={branch.book.id}>{branch.limbs.map(limb => <NaturalBranchWood key={limb.id} limb={limb} textureId={texture} />)}</g>)}
    <g mask={books.length ? `url(#${texture}-trunk)` : undefined} pointerEvents="none" aria-hidden="true"><TrunkSprite variant={variant} empty={!books.length} /></g>
    {items.map(({ branch, book }) => <g className="kt-branch" key={book.id} data-notebook-id={book.id}>
      <TreeAction label={`续读笔记本：${book.title}`} className="kt-book-action" onActivate={() => onNotebook(book)}>
        <title>{book.title} · 打开笔记本</title><path d={branch.hitPath} fill="none" stroke="transparent" strokeWidth="30" />
      </TreeAction>
    </g>)}
    {items.flatMap(({ book, leaves }) => leaves.map(leaf => <g key={leaf.section.id} data-note-id={leaf.section.id} data-notebook-id={book.id} onMouseEnter={() => show(book, leaf)} onMouseLeave={onLeave} onBlur={onLeave}>
      <TreeAction label={`打开知识点：${leaf.section.title}`} describedBy={previewNoteId === leaf.section.id ? previewId : undefined} className="home-tree-leaf" onActivate={() => onNote(book, leaf.section)} onFocus={() => show(book, leaf)}>
        <g data-leaf-paint="true" transform={`translate(${leaf.x},${leaf.y})`}>
          {/* A botanical terminal sprig shares one real Note; every painted leaf
              in this sprig opens that Note, with one keyboard entry. */}
          {[-62, 60].map((angle, index) => <g key={angle} transform={`rotate(${leaf.angle}) translate(0,3) rotate(${angle}) scale(.61) translate(0,-3)`}><LeafSprite variant={(leaf.variant + index + 1) % 4} /></g>)}
          <LeafSprite variant={previewNoteId === leaf.section.id ? 4 : leaf.variant} angle={leaf.angle} />
        </g>
        {[-62, 60].map(angle => <ellipse key={angle} transform={`translate(${leaf.x},${leaf.y}) rotate(${leaf.angle}) translate(0,3) rotate(${angle}) scale(.61) translate(0,-3)`} cx="0" cy="-30" rx="22" ry="33" fill="transparent" />)}
        <ellipse ref={element => { if (element) targets.current.set(leaf.section.id, element); else targets.current.delete(leaf.section.id) }} data-home-leaf-id={leaf.section.id} transform={`translate(${leaf.x},${leaf.y}) rotate(${leaf.angle})`} cx="0" cy="-30" rx="22" ry="33" fill="transparent" />
      </TreeAction>
    </g>))}
  </svg>
}
