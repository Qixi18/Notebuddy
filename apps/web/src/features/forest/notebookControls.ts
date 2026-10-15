import type { NotebookGeometry, KnowledgeLeaf } from './treeGeometry'
import { detailInteraction, operationSize } from './treeInteraction'

// A pair occupies two 44px rows with an 8px gap. At narrow initial zoom a pair
// is taller than the persisted 155-unit same-side branch tier. Project controls
// upward per tier, leaving the wood and all actual leaf slots untouched.
export function notebookControls(branch: NotebookGeometry, zoom: number) {
  const size = detailInteraction(zoom) ? operationSize(zoom) : 44
  const gap = 8 / Math.min(1, Math.max(.5, zoom))
  const extraTier = Math.max(0, 2 * (size + gap) - 155)
  const titleCenterY = branch.anchor.y + 39 - Math.floor(branch.book.tree_slot / 2) * extraTier
  const directoryCenterY = titleCenterY + size + gap
  return {
    size,
    titleCenterY,
    title: { x: branch.anchor.x + (branch.side < 0 ? -112 : -22), y: titleCenterY - size / 2, width: Math.max(134, size), height: size },
    directory: { x: branch.anchor.x + branch.side * 16 + (branch.side < 0 ? -128 : -8), y: directoryCenterY - size / 2, width: Math.max(136, size), height: size },
    directoryTranslate: { x: branch.anchor.x + branch.side * 16, y: directoryCenterY - 16 },
  }
}

export type NotebookControls = ReturnType<typeof notebookControls>
export type ControlItems = { branch: NotebookGeometry; leaves: KnowledgeLeaf[] }[]
type Rect = NotebookControls['title']
const overlap = (a: Rect, b: Rect, gap: number) => a.x < b.x + b.width + gap && a.x + a.width + gap > b.x && a.y < b.y + b.height + gap && a.y + a.height + gap > b.y

// Allocate paired controls against every real visible icon, before assigning
// proxy labels. Move the pair, never the leaf or the interactive stacking order.
export function projectNotebookControls(items: ControlItems, zoom: number): Map<string, NotebookControls> {
  const result = new Map<string, NotebookControls>()
  if (!detailInteraction(zoom)) {
    for (const { branch } of items) result.set(branch.book.id, notebookControls(branch, zoom))
    return result
  }
  const gap = 8 / Math.min(1, zoom)
  const icons = items.flatMap(({ leaves }) => leaves.map(leaf => ({ x: leaf.x, y: leaf.y - 25 })))
  const occupied: Rect[] = [{ x: -150, y: -100, width: 300, height: 145 }, { x: -92, y: 88 - operationSize(zoom) / 2, width: 184, height: operationSize(zoom) }]
  const free = (rect: Rect) => !occupied.some(other => overlap(rect, other, gap)) && !icons.some(icon => {
    const x = Math.max(rect.x, Math.min(icon.x, rect.x + rect.width)), y = Math.max(rect.y, Math.min(icon.y, rect.y + rect.height))
    return Math.hypot(icon.x - x, icon.y - y) < 11 + 2 / zoom
  })
  for (const { branch } of items) {
    const base = notebookControls(branch, zoom)
    const offsets = (limit: number) => [0, ...Array.from({ length: Math.floor(limit * zoom / 12) }, (_, i) => [-(i + 1) * 12 / zoom, (i + 1) * 12 / zoom]).flat()]
    const candidates = offsets(240).flatMap(dx => offsets(120).map(dy => ({ dx, dy }))).sort((a, b) => Math.abs(a.dx) + Math.abs(a.dy) - Math.abs(b.dx) - Math.abs(b.dy) || Math.abs(a.dy) - Math.abs(b.dy) || b.dx * branch.side - a.dx * branch.side)
    const moved = (dx: number, dy: number): NotebookControls => ({ ...base, titleCenterY: base.titleCenterY + dy, title: { ...base.title, x: base.title.x + dx, y: base.title.y + dy }, directory: { ...base.directory, x: base.directory.x + dx, y: base.directory.y + dy }, directoryTranslate: { x: base.directoryTranslate.x + dx, y: base.directoryTranslate.y + dy } })
    let placed: NotebookControls | undefined
    for (const { dx, dy } of candidates) {
      const next = moved(dx, dy)
      if (free(next.title) && free(next.directory)) { placed = next; break }
    }
    if (!placed) {
      // Very dense expanded banks can exhaust the nearby space. An outer lane
      // is safe for real icons and all previously allocated controls; fit uses
      // these exact projected rectangles rather than clipping knowledge leaves.
      const left = Math.min(...occupied.map(rect => rect.x), ...icons.map(icon => icon.x - 11))
      const right = Math.max(...occupied.map(rect => rect.x + rect.width), ...icons.map(icon => icon.x + 11))
      const dx = branch.side < 0 ? left - gap - Math.max(base.title.x + base.title.width, base.directory.x + base.directory.width) : right + gap - Math.min(base.title.x, base.directory.x)
      placed = moved(dx, 0)
    }
    occupied.push(placed.title, placed.directory)
    result.set(branch.book.id, placed)
  }
  return result
}
