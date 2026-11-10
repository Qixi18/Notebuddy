import type { GrowthTiming } from './timing'

const SVG = 'http://www.w3.org/2000/svg'
let serial = 0
type Animate = (element: Element, frames: Keyframe[], timing: GrowthTiming) => void

function node<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG, tag)
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value))
  return element
}

/** Decorations share the paint clock and local coordinates, never its hit areas. */
export function growthLights(root: SVGGElement, animate: Animate, cleanup: (undo: () => void) => void) {
  let paths = 0, leaves = 0, gradientId: string | undefined
  const glow = () => {
    if (gradientId) return `url(#${gradientId})`
    gradientId = `kt-growth-light-${++serial}`
    const defs = node('defs', { 'data-growth-light-defs': 'true' })
    const gradient = node('radialGradient', { id: gradientId })
    gradient.append(
      node('stop', { 'stop-color': '#fff5c2', 'stop-opacity': .95 }),
      node('stop', { offset: '.3', 'stop-color': '#e9ce70', 'stop-opacity': .64 }),
      node('stop', { offset: '.65', 'stop-color': '#bdc977', 'stop-opacity': .3 }),
      node('stop', { offset: '1', 'stop-color': '#bdc977', 'stop-opacity': 0 }),
    )
    defs.append(gradient); root.prepend(defs)
    cleanup(() => defs.remove())
    return `url(#${gradientId})`
  }
  const layer = (element: SVGElement, kind: string) => {
    const group = node('g', { 'data-growth-light': kind, 'pointer-events': 'none', 'aria-hidden': 'true' })
    const transform = element.getAttribute('transform')
    if (transform) group.setAttribute('transform', transform)
    element.after(group)
    cleanup(() => group.remove())
    return group
  }
  const path = (element: SVGElement, d: string, width: number, timing: GrowthTiming) => {
    if (paths++ >= 10) return
    const group = layer(element, 'path')
    const fill = glow()
    // A short luminous trail ends exactly at the mask's advancing tip.
    for (const [strokeWidth, color, opacity] of [[Math.min(18, width), '#d3d78b', .22], [5, '#efd58a', .65], [1.8, '#fff8d5', .95]] as const) {
      const trail = node('path', { d, fill: 'none', stroke: color, 'stroke-width': strokeWidth, opacity, 'stroke-linecap': 'round', pathLength: 1, 'stroke-dasharray': '.12 .88', 'stroke-dashoffset': '.12' })
      group.append(trail)
      animate(trail, [{ strokeDashoffset: '.12' }, { strokeDashoffset: '-.88' }], timing)
    }
    const tip = node('g', { 'data-growth-tip': 'true' })
    tip.style.offsetPath = `path('${d}')`
    tip.style.offsetAnchor = '0px 0px'
    tip.style.offsetPosition = '0px 0px'
    tip.style.offsetRotate = '0deg'
    tip.append(node('circle', { r: Math.max(22, Math.min(40, width * .9)), fill }), node('circle', { r: 4, fill: '#fff9d8' }), node('circle', { r: 1.8, fill: '#ffffff' }))
    group.append(tip)
    animate(tip, [{ offsetDistance: '0%' }, { offsetDistance: '100%' }], timing)
    const duration = timing.duration + 420
    animate(group, [{ opacity: 0 }, { opacity: 1, offset: .12 }, { opacity: .9, offset: timing.duration / duration }, { opacity: 0 }], { delay: timing.delay, duration, easing: 'linear' })
  }
  const leaf = (element: SVGElement, timing: GrowthTiming) => {
    if (leaves++ >= 12) return
    const group = layer(element, 'leaf')
    const aura = node('g', { transform: 'translate(0,-24)' })
    aura.append(node('circle', { r: 46, fill: glow() }), node('circle', { r: 20, fill: 'none', stroke: '#becb83', 'stroke-width': 1.2, opacity: .5 }))
    group.append(aura)
    animate(aura, [{ opacity: 0, scale: '.35' }, { opacity: .9, scale: '1', offset: .35 }, { opacity: 0, scale: '1.4' }], { delay: timing.delay, duration: 1450 })
    for (const [i, x] of [-22, 6, 25].entries()) {
      const spark = node('circle', { cx: 0, cy: -18, r: i === 1 ? 2.8 : 2, fill: i === 1 ? '#c1cf7c' : '#e4c365' })
      group.append(spark)
      animate(spark, [{ opacity: 0, transform: 'translate(0px, 0px) scale(.4)' }, { opacity: .9, offset: .24 }, { opacity: 0, transform: `translate(${x}px, ${-42 - i * 10}px) scale(.2)` }], { delay: timing.delay + 180 + i * 80, duration: 1100 })
    }
  }
  return { path, leaf }
}
