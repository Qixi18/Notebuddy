import type { KnowledgeLeaf, Point } from './treeGeometry'

/** Partition overlapping sprig targets by their real knowledge leaf centers.
 * Clipping only the transparent targets preserves the authored botanical art.
 */
export function leafHitCells(leaves: KnowledgeLeaf[]) {
  const centers = leaves.map(leaf => {
    const angle = leaf.angle * Math.PI / 180
    return { x: leaf.x + Math.sin(angle) * 30, y: leaf.y - Math.cos(angle) * 30 }
  })
  const result = new Map<string, Point[]>()
  if (!centers.length) return result
  const left = Math.min(...centers.map(point => point.x)) - 200
  const right = Math.max(...centers.map(point => point.x)) + 200
  const top = Math.min(...centers.map(point => point.y)) - 200
  const bottom = Math.max(...centers.map(point => point.y)) + 200
  centers.forEach((center, index) => {
    let cell: Point[] = [{ x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }]
    for (const other of centers) {
      if (center === other) continue
      const dx = other.x - center.x, dy = other.y - center.y
      const limit = (other.x * other.x + other.y * other.y - center.x * center.x - center.y * center.y) / 2
      const distance = (point: Point) => point.x * dx + point.y * dy - limit
      const clipped: Point[] = []
      for (let i = 0; i < cell.length; i++) {
        const a = cell[i], b = cell[(i + 1) % cell.length]
        const da = distance(a), db = distance(b)
        if (da <= 0) clipped.push(a)
        if ((da <= 0) !== (db <= 0)) {
          const t = da / (da - db)
          clipped.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t })
        }
      }
      cell = clipped
      if (!cell.length) break
    }
    result.set(leaves[index].section.id, cell)
  })
  return result
}
