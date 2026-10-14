import type { NotebookGeometry } from './treeGeometry'
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
