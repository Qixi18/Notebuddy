import type { KnowledgeLeaf, NotebookGeometry, Point } from './treeGeometry'
import { operationSize } from './treeInteraction'
import { notebookControls } from './notebookControls'

export type LabelRect = { x: number; y: number; width: number; height: number }
export type LeafLabel = { leaf: KnowledgeLeaf; branch: NotebookGeometry; rect: LabelRect; showText: boolean }
export const rectanglesOverlap = (a: LabelRect, b: LabelRect, gap = 0) => a.x < b.x + b.width + gap && a.x + a.width + gap > b.x && a.y < b.y + b.height + gap && a.y + a.height + gap > b.y

function branchPoints(branch: NotebookGeometry): Point[] {
  const { origin: o, anchor: a, side } = branch
  const segments = [
    [o, { x: side * 47, y: o.y - 20 }, { x: a.x - side * 23, y: a.y + 61 }, a],
    [a, { x: a.x + side * 16, y: a.y - 46 }, { x: a.x + side * 29, y: a.y - 103 }, { x: a.x + side * 29, y: a.y - 151 }],
  ]
  return segments.flatMap(([p0, p1, p2, p3]) => Array.from({ length: 25 }, (_, index) => {
    const t = index / 24, u = 1 - t
    return { x: u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t ** 3 * p3.x, y: u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t ** 3 * p3.y }
  }))
}

// Business leaf positions never move. Only text and its operation rectangle are
// assigned here, once across every visible main branch rather than per branch.
export function placeLeafLabels(items: { branch: NotebookGeometry; leaves: KnowledgeLeaf[] }[], zoom: number): LeafLabel[] {
  const size = operationSize(zoom)
  const width = Math.max(140, size), height = size
  const gap = 6 / Math.min(1, zoom)
  const occupied: LabelRect[] = items.flatMap(({ branch }) => {
    const controls = notebookControls(branch, zoom)
    return [controls.title, controls.directory]
  })
  const icons = items.flatMap(({ leaves }) => leaves.map(leaf => ({ id: leaf.section.id, rect: { x: leaf.x - 11, y: leaf.y - 36, width: 22, height: 22 } })))
  const wood = items.flatMap(({ branch }) => branchPoints(branch))
  const result: LeafLabel[] = []
  for (const { branch, leaves } of items) for (const leaf of leaves) {
    const preferredY = leaf.y - 30 - height / 2
    const columns = branch.side < 0 ? [-312, -112] : [172, -28]
    if (leaf.section.tree_slot % 2) columns.reverse()
    let placed: LabelRect | undefined
    const safe = (rect: LabelRect) => !occupied.some(other => rectanglesOverlap(rect, other, gap)) && !icons.some(icon => icon.id !== leaf.section.id && rectanglesOverlap(rect, icon.rect, 2))
    const offsets = [0, ...Array.from({ length: Math.floor(120 / (12 / zoom)) }, (_, row) => [-(row + 1) * 12 / zoom, (row + 1) * 12 / zoom]).flat()]
    for (const offset of offsets) {
      if (placed) break
      for (const x of columns) {
        const rect = { x, y: preferredY + offset, width, height }
        const textBounds = { x: x + 4, y: rect.y + height / 2 - 12 / zoom, width: width - 8, height: 18 / zoom }
        // Transparent hit area may cross a twig, but the readable text and its
        // small paper wash stay clear of the wood; no white block splits joints.
        const overTrunk = rectanglesOverlap(textBounds, { x: -70, y: -480, width: 140, height: 480 })
        const overWood = wood.some(point => point.x > textBounds.x - 5 && point.x < textBounds.x + textBounds.width + 5 && point.y > textBounds.y - 5 && point.y < textBounds.y + textBounds.height + 5)
        if (!overTrunk && !overWood && safe(rect)) { placed = rect; break }
      }
    }
    const showText = Boolean(placed)
    // Dense secondary labels use a nearby 44px operation badge and the explicit
    // notebook directory. Never create an unbounded tower or long vertical lines.
    if (!placed) for (const yOffset of offsets) {
      if (placed) break
      for (const xOffset of offsets) {
        const rect = { x: leaf.x - size / 2 + xOffset, y: leaf.y - 25 - size / 2 + yOffset, width: size, height: size }
        if (safe(rect)) { placed = rect; break }
      }
    }
    // With very dense expanded banks the directory remains the full, 44px
    // accessible operation surface; the exact painted leaf still has its icon.
    if (!placed) continue
    occupied.push(placed)
    result.push({ leaf, branch, rect: placed, showText })
  }
  return result
}
