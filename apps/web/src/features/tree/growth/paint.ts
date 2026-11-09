import { TREE_GROWTH_EASING, TREE_GROWTH_LIFETIME_MS, VINE_GROWTH_EASING, VINE_GROWTH_TRAVEL_MS, type GrowthTiming } from './timing'
import { growthLights } from './lights'
import { paintVineFlow, type VineFlowOptions } from '../motion/vineFlow'
import { vinePoint, type Point, type VineGeometry } from '../vineGeometry'
import type { Motion } from '../motion/playback'

export type Playback = { finished: Promise<void>; finish: () => void }
export type TreeGrowth = { course: boolean; books: Set<string>; notes: Set<string> }
const SVG = 'http://www.w3.org/2000/svg'
let serial = 0
type Timing = GrowthTiming
const sectionKey = (bookId: string, blockId: string) => JSON.stringify([bookId, blockId])

/** Temporary masks affect paint only; every resource is removed on every exit. */
function painter(root: SVGGElement, timeScale = 1) {
  const effects: Animation[] = [], undo: (() => void)[] = []
  const startTime = document.timeline?.currentTime
  let done = false, timer: ReturnType<typeof setTimeout> | undefined, resolve!: () => void
  const finished = new Promise<void>(r => { resolve = r })
  const finish = () => {
    if (done) return
    done = true
    clearTimeout(timer)
    for (const effect of effects) { try { effect.cancel() } catch { /* Complete the remaining cleanup. */ } }
    for (const cleanup of undo.reverse()) cleanup()
    resolve()
  }
  const animate = (element: Element, frames: Keyframe[], timing: Timing) => {
    const effect = element.animate(frames, { delay: Math.round(timing.delay * timeScale), duration: Math.round(timing.duration * timeScale), easing: timing.easing ?? 'cubic-bezier(.22,.61,.36,1)', fill: 'both' })
    if (typeof startTime === 'number') effect.startTime = startTime
    effects.push(effect)
  }
  const motion: Motion = { animate: (element, frames, timing) => animate(element, frames, { ...timing, delay: timing.delay ?? 0 }), cleanup: restore => undo.push(restore) }
  const lights = growthLights(root, animate, cleanup => undo.push(cleanup))
  const mask = (element: SVGGraphicsElement, path: string, width: number, timing: Timing, luminous = false, converge = false) => {
    const defs = document.createElementNS(SVG, 'defs')
    defs.dataset.growthDefs = 'true'
    const mask = document.createElementNS(SVG, 'mask'), line = document.createElementNS(SVG, 'path')
    mask.id = `kt-growth-mask-${++serial}`
    const bounds = element.getBBox()
    for (const [name, value] of Object.entries({ maskUnits: 'userSpaceOnUse', maskContentUnits: 'userSpaceOnUse', x: String(bounds.x - 4), y: String(bounds.y - 4), width: String(bounds.width + 8), height: String(bounds.height + 8) })) mask.setAttribute(name, value)
    for (const [name, value] of Object.entries({ d: path, fill: 'none', stroke: 'white', 'stroke-width': String(width), 'stroke-linecap': 'round', pathLength: '1', 'stroke-dasharray': '1', 'stroke-dashoffset': '1' })) line.setAttribute(name, value)
    mask.append(line); defs.append(mask); root.prepend(defs)
    const previous = element.getAttribute('mask')
    element.setAttribute('mask', `url(#${mask.id})`)
    undo.push(() => { if (previous === null) element.removeAttribute('mask'); else element.setAttribute('mask', previous); defs.remove() })
    if (converge) {
      line.setAttribute('stroke-linecap', 'butt')
      line.dataset.growthFront = 'start'
      const reverse = line.cloneNode(true) as SVGPathElement
      reverse.dataset.growthFront = 'end'
      reverse.setAttribute('stroke-dashoffset', '-1')
      mask.append(reverse)
      animate(line, [{ strokeDashoffset: '1' }, { strokeDashoffset: '.5' }], timing)
      animate(reverse, [{ strokeDashoffset: '-1' }, { strokeDashoffset: '-.5' }], timing)
    } else animate(line, [{ strokeDashoffset: '1' }, { strokeDashoffset: '0' }], timing)
    if (luminous) lights.path(element, path, width, timing)
  }
  const leaf = (element: SVGElement, timing: Timing, luminous = false) => {
    const old = element.getAttribute('style')
    element.style.transformOrigin = element.dataset.growthOrigin ?? '0px 3px'
    undo.push(() => { if (old === null) element.removeAttribute('style'); else element.setAttribute('style', old) })
    const frames = [{ opacity: 0, transform: 'scale(.12,.2)' }, ...(luminous ? [{ opacity: 1, transform: 'scale(1.045,1.07)', offset: .78 }] : []), { opacity: 1, transform: 'scale(1,1)' }]
    animate(element, frames, timing)
    if (luminous) lights.leaf(element, timing)
  }
  const sprout = (element: SVGPathElement, timing: Timing) => {
    const oldStyle = element.getAttribute('style'), oldLength = element.getAttribute('pathLength')
    element.setAttribute('pathLength', '1')
    element.style.strokeDasharray = '1'
    element.style.strokeDashoffset = '1'
    undo.push(() => {
      if (oldStyle === null) element.removeAttribute('style'); else element.setAttribute('style', oldStyle)
      if (oldLength === null) element.removeAttribute('pathLength'); else element.setAttribute('pathLength', oldLength)
    })
    animate(element, [{ opacity: 0, strokeDashoffset: '1' }, { opacity: 1, strokeDashoffset: '0' }], timing)
  }
  const run = (build: () => void): Playback => {
    try {
      build()
      if (!effects.length) finish()
      else {
        void Promise.all(effects.map(effect => effect.finished)).then(finish, finish)
        timer = setTimeout(finish, Math.round(TREE_GROWTH_LIFETIME_MS * timeScale))
      }
    } catch { finish() }
    return { finished, finish }
  }
  return { animate, mask, leaf, sprout, motion, run }
}

export function playTreeGrowth(root: SVGGElement, growth: TreeGrowth, timeScale = 1): Playback {
  const paint = painter(root, timeScale)
  return paint.run(() => {
    const limbs = [...root.querySelectorAll<SVGGElement>('[data-growth-limb]')]
    const timings = new Map<string, Timing>()
    const selected = limbs.filter(l => {
      const note = l.dataset.growthNote && l.dataset.growthBook
        ? sectionKey(l.dataset.growthBook, l.dataset.growthNote) : undefined
      return growth.course || growth.books.has(l.dataset.growthBook!) || Boolean(note && growth.notes.has(note))
    })
    const byId = new Map(selected.map(l => [l.dataset.growthLimb!, l]))
    const schedule = (limb: SVGGElement): Timing => {
      const id = limb.dataset.growthLimb!
      if (timings.has(id)) return timings.get(id)!
      const parent = byId.get(limb.dataset.growthParent!)
      const base = parent ? schedule(parent) : { delay: growth.course ? 700 : 0, duration: 0 }
      const level = Number(limb.dataset.growthLevel)
      const value = { delay: level === 0 && growth.course ? 0 : base.delay + base.duration * Number(limb.dataset.growthParentT ?? 1), duration: level === 0 ? 900 : level === 1 ? 1250 : level === 2 ? 900 : 600, easing: TREE_GROWTH_EASING }
      timings.set(id, value); return value
    }
    for (const limb of selected) paint.mask(limb, limb.dataset.growthPath!, Number(limb.dataset.growthRadius) * 2 + 8, schedule(limb), true)
    let index = 0
    for (const element of root.querySelectorAll<SVGGElement>('[data-growth-leaf]')) {
      const id = element.dataset.growthLeaf!
      const bookId = element.dataset.growthBook!
      if (!growth.course && !growth.books.has(bookId) && !growth.notes.has(id)) continue
      const twigLimb = limbs.find(limb => limb.dataset.growthBook === bookId && limb.dataset.growthNote
        && sectionKey(bookId, limb.dataset.growthNote) === id)
      const twig = twigLimb ? timings.get(twigLimb.dataset.growthLimb!) : undefined
      paint.leaf(element, { delay: twig ? twig.delay + twig.duration - 120 : (growth.course ? 2000 : 220) + Math.min(600, index++ * 85), duration: 900, easing: TREE_GROWTH_EASING }, true)
    }
    if (growth.course) {
      const trunk = root.querySelector<SVGGElement>('[data-growth-trunk]')
      if (trunk && !trunk.querySelector('[data-growth-limb]')) {
        const bounds = trunk.getBBox()
        paint.mask(trunk, `M${bounds.x + bounds.width / 2},${bounds.y + bounds.height}V${bounds.y}`, bounds.width + 4, { delay: 0, duration: 1000, easing: TREE_GROWTH_EASING }, true)
      }
      for (const shadow of root.querySelectorAll<SVGElement>('[data-growth-shadow]')) paint.animate(shadow, [{ opacity: 0 }, { opacity: .14 }], { delay: 0, duration: 180 })
      for (const [i, bough] of [...root.querySelectorAll<SVGGraphicsElement>('[data-growth-sapling-path]')].entries()) paint.mask(bough, bough.dataset.growthSaplingPath!, 28, { delay: 760 + i * 80, duration: 1250, easing: TREE_GROWTH_EASING }, true)
      for (const [i, foliage] of [...root.querySelectorAll<SVGElement>('[data-growth-sapling-foliage]')].entries()) paint.animate(foliage, [{ opacity: 0 }, { opacity: 1 }], { delay: 1900 + i * 80, duration: 900 })
    }
  })
}

export type VineGrowthGuide = { vine: VineGeometry; relationId: string; options: VineFlowOptions }

/** Arc-length arrival for real attachment points, including curved / hanging vines. */
function vineArrival(vine: VineGeometry) {
  const points = Array.from({ length: 257 }, (_, i) => vinePoint(vine.curves, i / 256))
  const lengths = points.slice(1).map((point, i) => Math.hypot(point.x - points[i].x, point.y - points[i].y))
  const total = lengths.reduce((sum, length) => sum + length, 0)
  return (point: Point) => {
    let closest = Infinity, walked = 0, distance = 0
    for (let i = 0; i < lengths.length; i++) {
      const a = points[i], b = points[i + 1], dx = b.x - a.x, dy = b.y - a.y
      const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / (lengths[i] ** 2 || 1)))
      const error = (point.x - a.x - dx * t) ** 2 + (point.y - a.y - dy * t) ** 2
      if (error < closest) { closest = error; distance = walked + lengths[i] * t }
      walked += lengths[i]
    }
    const fraction = total ? distance / total : 0
    return Math.max(0, Math.ceil(2 * Math.min(fraction, 1 - fraction) * VINE_GROWTH_TRAVEL_MS - 1e-6))
  }
}

export function playVineGrowth(root: SVGGElement, ids: Set<string>, stems: Set<string>, guides: VineGrowthGuide[] = []): Playback {
  const paint = painter(root)
  return paint.run(() => {
    const byGroup = new Map(guides.map(guide => [guide.vine.id, guide]))
    const clocks = new Map(guides.map(guide => [guide.vine.id, vineArrival(guide.vine)]))
    for (const element of root.querySelectorAll<SVGGElement>('[data-growth-vine-path]')) if (stems.has(element.dataset.growthVineGroup!)) {
      paint.mask(element, element.dataset.growthVinePath!, 16, { delay: 0, duration: VINE_GROWTH_TRAVEL_MS, easing: VINE_GROWTH_EASING }, false, true)
    }
    for (const guide of guides) if (stems.has(guide.vine.id)) paintVineFlow(root, guide.vine, guide.relationId, guide.options, paint.motion)
    for (const path of root.querySelectorAll<SVGPathElement>('[data-growth-relation-petiole], [data-growth-vine-tendril]')) {
      const group = path.dataset.growthVineGroup!
      const selectedLeaf = path.dataset.growthRelationPetiole && ids.has(path.dataset.growthRelationPetiole)
      if (!stems.has(group) && !selectedLeaf) continue
      const coordinates = path.getAttribute('d')?.match(/[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?/gi)
      const delay = stems.has(group) && coordinates ? clocks.get(group)?.({ x: Number(coordinates[0]), y: Number(coordinates[1]) }) ?? 0 : 0
      paint.sprout(path, { delay, duration: 360, easing: VINE_GROWTH_EASING })
    }
    let index = 0
    for (const element of root.querySelectorAll<SVGGElement>('[data-growth-relation-leaf]')) {
      if (!ids.has(element.dataset.growthRelationLeaf!) && !stems.has(element.dataset.growthVineGroup!)) continue
      const group = element.dataset.growthVineGroup!, guide = byGroup.get(group)
      const arrival = stems.has(group) ? guide ? clocks.get(group)!(vinePoint(guide.vine.curves, Number(element.dataset.growthVineT ?? .5))) : VINE_GROWTH_TRAVEL_MS : 0
      paint.leaf(element, { delay: stems.has(group) ? arrival + 180 : 180 + Math.min(200, index++ * 45), duration: 520 })
    }
  })
}
