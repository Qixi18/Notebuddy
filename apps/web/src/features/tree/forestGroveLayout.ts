import { TREE_SPACING, type TreePosition } from './layout'

export const FOREST_SPACING = 820
export const FOREST_LAYOUT_VERSION = 'grove-v1'
export const FOREST_CAPTION_BOTTOM = 170
export type GroveTreePosition = TreePosition & { grove: number; captionY: number }

/** Stable physical slots form loose groves; metadata refreshes never shuffle trees. */
export function arrangeForestGroves(trees: TreePosition[], spacing = FOREST_SPACING): GroveTreePosition[] {
  const roots = trees.map(tree => {
    const slot = Math.max(0, Math.round((tree.x - 280) / TREE_SPACING))
    const lane = slot % 3
    return { ...tree, grove: Math.floor(slot / 3),
      x: (tree.x - 280) / TREE_SPACING * spacing + spacing / 2 + ((tree.seed >>> 4) % 51) - 25,
      y: 750 + (tree.y - 750) * .35 + [115, -125, 35][lane] + ((tree.seed >>> 8) % 35) - 17 }
  })
  const floors = new Map<number, number>()
  for (const tree of roots) floors.set(tree.grove, Math.max(floors.get(tree.grove) ?? -Infinity, tree.y))
  return roots.map(tree => ({ ...tree, captionY: floors.get(tree.grove)! + 76 }))
}

/** Fit the actual crown and the aligned information/actions below its grove. */
export function forestTreeFrame(tree: TreePosition, bounds: { x: number; y: number; width: number; height: number }) {
  return [
    { x: tree.x + Math.min(-290, bounds.x), y: tree.y + bounds.y },
    { x: tree.x + Math.max(290, bounds.x + bounds.width), y: (tree.captionY ?? tree.y + 76) + FOREST_CAPTION_BOTTOM },
  ]
}
