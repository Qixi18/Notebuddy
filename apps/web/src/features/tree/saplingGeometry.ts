import type { Point } from './treeGeometry'

type Curve = [Point, Point, Point, Point]
function pointAt([a, b, c, d]: Curve, t: number): Point {
  const u = 1 - t
  return { x: u ** 3 * a.x + 3 * u ** 2 * t * b.x + 3 * u * t ** 2 * c.x + t ** 3 * d.x, y: u ** 3 * a.y + 3 * u ** 2 * t * b.y + 3 * u * t ** 2 * c.y + t ** 3 * d.y }
}
const coordinate = (point: Point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`

// These junctions lie inside the bark of the three 330px trunk crops.
// All foliage is decorative; no course, notebook or Note IDs are generated here.
export function saplingGeometry(variant: number) {
  const junctions = [
    [{ x: 23, y: -214 }, { x: 10, y: -268 }, { x: -1, y: -303 }],
    [{ x: 10, y: -213 }, { x: -5, y: -266 }, { x: -18, y: -304 }],
    [{ x: 9, y: -211 }, { x: 5, y: -268 }, { x: -7, y: -302 }],
  ][variant % 3]
  const [lower, middle, top] = junctions
  const curves: Curve[] = [
    [lower, { x: -36, y: -222 }, { x: -122, y: -265 }, { x: -167, y: -316 }],
    [middle, { x: -52, y: -291 }, { x: -97, y: -353 }, { x: -112, y: -395 }],
    [top, { x: -38, y: -332 }, { x: -58, y: -397 }, { x: -31, y: -437 }],
    [top, { x: 14, y: -333 }, { x: 48, y: -387 }, { x: 68, y: -427 }],
    [middle, { x: 55, y: -286 }, { x: 102, y: -337 }, { x: 129, y: -372 }],
    [lower, { x: 66, y: -221 }, { x: 132, y: -252 }, { x: 169, y: -296 }],
  ]
  return curves.map((curve, index) => {
    const direction = (t: number) => {
      const a = pointAt(curve, Math.max(0, t - .005)), b = pointAt(curve, Math.min(1, t + .005))
      const length = Math.hypot(b.x - a.x, b.y - a.y)
      return { x: (b.x - a.x) / length, y: (b.y - a.y) / length }
    }
    const edge = (side: number) => Array.from({ length: 21 }, (_, i) => {
      const t = i / 20, p = pointAt(curve, t), tangent = direction(t)
      const width = .45 + (index % 2 ? 3.8 : 5.2) * (1 - t) ** 1.4
      return { x: p.x - tangent.y * width * side, y: p.y + tangent.x * width * side }
    })
    const outline = [...edge(1), ...edge(-1).reverse()]
    const foliage = [.37, .57, .77, .94, 1].flatMap((t, leafIndex) => {
      const root = pointAt(curve, t), tangent = direction(t)
      const side = (leafIndex + index) % 2 ? -1 : 1
      const reach = leafIndex === 4 ? 6 : 20 + (index + leafIndex) % 3 * 4
      const dx = leafIndex === 4 ? tangent.x * reach : -tangent.y * side * reach + tangent.x * 9
      const dy = leafIndex === 4 ? tangent.y * reach : Math.min(-9, tangent.x * side * reach + tangent.y * 9)
      const petiole = { x: root.x + dx, y: root.y + dy }
      const control = { x: root.x + dx * .6, y: root.y - 5 }
      const terminal = {
        petiole, angle: Math.atan2(dx, -dy) * 180 / Math.PI,
        scale: .57 + ((index * 3 + leafIndex) % 4) * .05,
        variant: (index * 2 + leafIndex + variant) % 6,
        path: `M${coordinate(root)} Q${coordinate(control)} ${coordinate(petiole)}`,
      }
      if (leafIndex === 4) return [terminal]
      // A sprig carries a terminal leaf and two smaller side leaves. The fork
      // follows the exact parent stem before branching, so no leaf can float.
      const length = Math.hypot(dx, dy)
      const sideLeaves = [.42, .72].map((fork, forkIndex) => {
        const u = 1 - fork
        const junction = { x: u * u * root.x + 2 * u * fork * control.x + fork * fork * petiole.x, y: u * u * root.y + 2 * u * fork * control.y + fork * fork * petiole.y }
        const sign = forkIndex ? 1 : -1
        const leafDx = -dy / length * sign * 17 + dx * .12
        const leafDy = Math.min(-5, dx / length * sign * 17 + dy * .12)
        const end = { x: junction.x + leafDx, y: junction.y + leafDy }
        const incoming = { x: root.x + (control.x - root.x) * fork, y: root.y + (control.y - root.y) * fork }
        return { petiole: end, angle: Math.atan2(leafDx, -leafDy) * 180 / Math.PI, scale: terminal.scale * .82, variant: (terminal.variant + forkIndex + 2) % 6,
          path: `M${coordinate(root)} Q${coordinate(incoming)} ${coordinate(junction)} Q${coordinate({ x: junction.x + leafDx * .5, y: junction.y - 3 })} ${coordinate(end)}` }
      })
      return [...sideLeaves, terminal]
    })
    return { outline: `M${outline.map(coordinate).join(' L')}Z`, spine: `M${coordinate(curve[0])} C${curve.slice(1).map(coordinate).join(' ')}`, foliage }
  })
}
