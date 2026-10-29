import { TREE_SPACING, type TreePosition } from './layout'

export const FOREST_SPACING = 820
export const FOREST_LAYOUT_VERSION = 'grove-v2-grounded'
export const FOREST_CAPTION_BOTTOM = 170
export const FOREST_ROOT_CAPTION_Y = 40
export type GroveTreePosition = TreePosition & { grove: number; captionY: number }

/** Stable physical slots form loose groves; metadata refreshes never shuffle trees. */
export function arrangeForestGroves(trees: TreePosition[], spacing = FOREST_SPACING): GroveTreePosition[] {
  const roots = trees.map(tree => {
    const slot = Math.max(0, Math.round((tree.x - 280) / TREE_SPACING))
    const lane = slot % 3
    return { ...tree, grove: Math.floor(slot / 3),
      x: (tree.x - 280) / TREE_SPACING * spacing + spacing / 2 + ((tree.seed >>> 4) % 51) - 25,
      y: 750 + (tree.y - 750) * .35 + [45, -28, 10][lane] + ((tree.seed >>> 8) % 35) - 17 }
  })
  return roots.map(tree => ({ ...tree, captionY: tree.y + FOREST_ROOT_CAPTION_Y }))
}

/** Include the root bed, crown, and course actions in fit and focus views. */
export function forestTreeFrame(tree: TreePosition, bounds: { x: number; y: number; width: number; height: number }) {
  return [
    { x: tree.x + Math.min(-350, bounds.x), y: tree.y + bounds.y },
    { x: tree.x + Math.max(350, bounds.x + bounds.width), y: (tree.captionY ?? tree.y + FOREST_ROOT_CAPTION_Y) + FOREST_CAPTION_BOTTOM },
  ]
}
