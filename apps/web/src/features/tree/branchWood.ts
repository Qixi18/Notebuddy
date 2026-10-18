import { curveCatmullRom, curveCatmullRomClosed, line } from 'd3-shape'
import { hashId } from './layout'
import type { KnowledgeLeaf, NotebookGeometry, Point } from './treeGeometry'

type Cubic = [Point, Point, Point, Point]
const mix = (a: Point, b: Point, t: number): Point => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t })
function cubic(points: Cubic, t: number) {
  const a = mix(points[0], points[1], t), b = mix(points[1], points[2], t), c = mix(points[2], points[3], t)
  return mix(mix(a, b, t), mix(b, c, t), t)
}
const openPath = line<Point>().x(p => p.x).y(p => p.y).curve(curveCatmullRom.alpha(.5))
const closedPath = line<Point>().x(p => p.x).y(p => p.y).curve(curveCatmullRomClosed.alpha(.5))

// Paint geometry only: never changes the persisted book/Note slots or hit geometry.
// Offset a continuous cubic spine along its normal, rather than closing two
// unrelated curves into the old flat spear. The last bank extends the same limb.
export function branchWood(branch: NotebookGeometry, leaves: KnowledgeLeaf[]) {
  const { origin, anchor, side } = branch
  const seed = hashId(branch.book.id)
  const rise = Math.max(151, ...leaves.map(leaf => anchor.y - leaf.stem.y + 25))
  const reach = Math.max(29, ...leaves.map(leaf => (leaf.stem.x - anchor.x) * side + 8))
  const tip = { x: anchor.x + side * reach, y: anchor.y - rise }
  const incoming = { x: anchor.x - side * 23, y: anchor.y + 61 }
  const lower: Cubic = [origin, { x: side * 47, y: origin.y - 20 }, incoming, anchor]
  const upper: Cubic = [anchor, { x: anchor.x + side * 12.65, y: anchor.y - 33.55 }, { x: tip.x - side * (11 + seed % 7), y: tip.y + rise * .28 }, tip]
  const pointAt = (t: number) => t <= .5 ? cubic(lower, t * 2) : cubic(upper, (t - .5) * 2)
  const normalAt = (t: number) => {
    const a = pointAt(Math.max(0, t - .001)), b = pointAt(Math.min(1, t + .001))
    const length = Math.hypot(b.x - a.x, b.y - a.y)
    return { x: -(b.y - a.y) / length, y: (b.x - a.x) / length }
  }
  const samples = Array.from({ length: 29 }, (_, i) => {
    const t = i / 28
    return { point: pointAt(t), normal: normalAt(t), width: .28 + (13 + seed % 4) * (1 - t) ** 1.35 }
  })
  const edge = (sign: number) => samples.map(({ point, normal, width }) => ({ x: point.x + normal.x * width * sign, y: point.y + normal.y * width * sign }))
  const outline = closedPath([...edge(1), ...edge(-1).reverse()])!
  // Fourteen overlapping texture spans follow the tangent. The shared atlas
  // pattern keeps grain at a fixed world scale instead of stretching it by book.
  const textureSpans = Array.from({ length: 14 }, (_, i) => {
    const start = pointAt(i / 14), end = pointAt((i + 1) / 14)
    return { center: mix(start, end, .5), angle: Math.atan2(end.y - start.y, end.x - start.x) * 180 / Math.PI + 90, length: Math.hypot(end.x - start.x, end.y - start.y) + 14 }
  })
  const bark = Array.from({ length: 8 }, (_, i) => {
    const start = .09 + i * .105 + (seed % 5) * .002
    const offset = ((seed + i * 7) % 9 - 4) / 5
    const points = [0, .025, .06].map(dt => {
      const t = Math.min(.97, start + dt), p = pointAt(t), n = normalAt(t)
      const width = (13 + seed % 4) * (1 - t) ** 1.35
      return { x: p.x + n.x * offset * width, y: p.y + n.y * offset * width }
    })
    return openPath(points)!
  })
  const twigs = leaves.map(leaf => {
    // Find a real point on the monotonic upper spine near this leaf's petiole.
    const targetY = Math.min(anchor.y, leaf.stem.y + 19)
    let low = .5, high = 1
    for (let i = 0; i < 22; i++) {
      const mid = (low + high) / 2
      if (pointAt(mid).y > targetY) low = mid
      else high = mid
    }
    const position = (low + high) / 2, root = pointAt(position)
    const end = { x: leaf.x, y: leaf.y + 3 }
    return { noteId: leaf.section.id, root, end, position, path: `M${root.x},${root.y} Q${leaf.stem.x - side * 7},${leaf.stem.y + 9} ${leaf.stem.x},${leaf.stem.y} Q${leaf.x - (leaf.x - leaf.stem.x) * .4},${leaf.y + 9} ${end.x},${end.y}` }
  })
  return { outline, samples, textureSpans, bark, twigs, pointAt }
}
