import { vinePoint, type Point, type VineGeometry } from '../vineGeometry'
import { decorativePlayback, type Motion } from './playback'
import { VINE_GROWTH_EASING, VINE_GROWTH_TRAVEL_MS } from '../growth/timing'

export type VineFlow = { reverse: boolean; source?: Point; target?: Point }
export type VineFlowOptions = VineFlow & { delay?: number; screenScale: number }
const SVG = 'http://www.w3.org/2000/svg'
let serial = 0
function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG, tag)
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value))
  return element
}

function midpoint(path: SVGPathElement, vine: VineGeometry): Point {
  if (typeof path.getTotalLength === 'function' && typeof path.getPointAtLength === 'function') {
    const point = path.getPointAtLength(path.getTotalLength() / 2)
    return { x: point.x, y: point.y }
  }
  // Geometry-only fallback for renderers without native SVG length measurement.
  const points = Array.from({ length: 129 }, (_, i) => vinePoint(vine.curves, i / 128))
  const lengths = points.slice(1).map((point, i) => Math.hypot(point.x - points[i].x, point.y - points[i].y))
  let remaining = lengths.reduce((total, length) => total + length, 0) / 2
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i]) {
      const t = lengths[i] ? remaining / lengths[i] : 0
      return { x: points[i].x + (points[i + 1].x - points[i].x) * t, y: points[i].y + (points[i + 1].y - points[i].y) * t }
    }
    remaining -= lengths[i]
  }
  return points.at(-1)!
}

/** Two luminous fronts leave the actual vine ends together and merge at half length. */
export function playVineFlow(root: SVGGElement, vine: VineGeometry, relationId: string, options: VineFlowOptions) {
  return decorativePlayback(root, motion => paintVineFlow(root, vine, relationId, options, motion))
}

/** Creation reuses its stem painter's exact animation clock and cleanup. */
export function paintVineFlow(root: SVGGElement, vine: VineGeometry, relationId: string, options: VineFlowOptions, motion: Motion) {
    const group = svg('g', { 'data-vine-flow': relationId, 'pointer-events': 'none', 'aria-hidden': 'true' })
    root.append(group)
    motion.cleanup(() => group.remove())
    const id = `nb-vine-flow-${++serial}`
    const defs = svg('defs', { 'data-flow-defs': 'true' }), gradient = svg('radialGradient', { id })
    gradient.append(svg('stop', { 'stop-color': '#fff7cc', 'stop-opacity': .98 }), svg('stop', { offset: '.28', 'stop-color': '#e8cf79', 'stop-opacity': .7 }), svg('stop', { offset: '.65', 'stop-color': '#c0cc80', 'stop-opacity': .3 }), svg('stop', { offset: '1', 'stop-color': '#c0cc80', 'stop-opacity': 0 }))
    const guide = svg('path', { d: vine.centerline })
    defs.append(gradient, guide); group.append(defs)
    const scale = Math.max(.15, options.screenScale), delay = options.delay ?? 0
    const travel = VINE_GROWTH_TRAVEL_MS
    const start = vine.curves[0][0], end = vine.curves.at(-1)![3]
    const source = options.source ?? (options.reverse ? end : start)
    const target = options.target ?? (options.reverse ? start : end)
    const pulse = (point: Point, kind: string, startDelay: number) => {
      const light = svg('circle', { [`data-flow-${kind}`]: 'true', cx: point.x, cy: point.y, r: 32 / scale, fill: `url(#${id})` })
      group.append(light)
      motion.animate(light, [{ opacity: 0 }, { opacity: .9, offset: .3 }, { opacity: 0 }], { delay: startDelay, duration: 780 })
    }
    pulse(source, 'source', delay)
    pulse(target, 'target', delay)
    for (let i = 0; i < 2; i++) {
      const fromEnd = i === 0 ? options.reverse : !options.reverse
      const beam = svg('g', { 'data-flow-beam': i === 0 ? 'source' : 'target' })
      group.append(beam)
      for (const [width, opacity, color] of [[12, .18, '#c6d289'], [5, .6, '#ebd180'], [1.8, .95, '#fff9d9']] as const) {
        const trail = svg('path', { 'data-flow-trail': 'true', d: vine.centerline, fill: 'none', stroke: color, 'stroke-width': width / scale,
          'stroke-linecap': 'round', opacity, pathLength: 1, 'stroke-dasharray': '.12 2' })
        beam.append(trail)
        motion.animate(trail, [{ strokeDashoffset: fromEnd ? '-1' : '.12' }, { strokeDashoffset: fromEnd ? '-.5' : '-.38' }], { delay, duration: travel, easing: VINE_GROWTH_EASING })
      }
      const packet = svg('g', { 'data-flow-packet': i === 0 ? 'source' : 'target' })
      packet.style.offsetPath = `path('${vine.centerline}')`
      packet.style.offsetAnchor = '0px 0px'
      packet.style.offsetPosition = '0px 0px'
      packet.style.offsetRotate = '0deg'
      packet.append(svg('circle', { r: 24 / scale, fill: `url(#${id})` }), svg('circle', { r: 3.7 / scale, fill: '#fff9d9' }), svg('circle', { r: 1.5 / scale, fill: '#fff' }))
      beam.append(packet)
      motion.animate(packet, [
        { offsetDistance: fromEnd ? '100%' : '0%' }, { offsetDistance: '50%' },
      ], { delay, duration: travel, easing: VINE_GROWTH_EASING })
      motion.animate(beam, [{ opacity: 0 }, { opacity: 1, offset: .1 }, { opacity: 1, offset: travel / (travel + 420) }, { opacity: 0 }], { delay, duration: travel + 420, easing: 'linear' })
    }
    const center = midpoint(guide, vine)
    const meeting = svg('g', { 'data-flow-meeting': 'true', transform: `translate(${center.x},${center.y})` })
    const bloom = svg('g', { 'data-flow-bloom': 'true' })
    bloom.append(svg('circle', { r: 48 / scale, fill: `url(#${id})` }), svg('circle', { r: 6 / scale, fill: '#fff8ce' }))
    meeting.append(bloom); group.append(meeting)
    motion.animate(bloom, [{ opacity: 0, transform: 'scale(.25)' }, { opacity: 1, transform: 'scale(1.05)', offset: .28 }, { opacity: 0, transform: 'scale(1.65)' }], { delay: delay + travel - 60, duration: 1150 })
    const ring = svg('circle', { r: 12 / scale, fill: 'none', stroke: '#e2cb7c', 'stroke-width': 1.3 / scale })
    meeting.append(ring)
    motion.animate(ring, [{ opacity: 0, transform: 'scale(.4)' }, { opacity: .65, offset: .2 }, { opacity: 0, transform: 'scale(3.2)' }], { delay: delay + travel, duration: 1050 })
    for (let i = 0; i < 6; i++) {
      const angle = i * Math.PI / 3 - Math.PI / 2
      const spark = svg('circle', { r: (i % 2 ? 2 : 2.6) / scale, fill: i % 2 ? '#c3d08a' : '#e9cc76' })
      meeting.append(spark)
      motion.animate(spark, [{ opacity: 0, transform: 'translate(0px,0px) scale(.3)' }, { opacity: .95, offset: .2 },
        { opacity: 0, transform: `translate(${Math.cos(angle) * 38 / scale}px,${Math.sin(angle) * 38 / scale}px) scale(.1)` }], { delay: delay + travel, duration: 1100 })
    }
}
