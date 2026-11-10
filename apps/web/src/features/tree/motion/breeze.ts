import { decorativePlayback } from './playback'

/** One visible gust ripples through the crown, then settles with fixed roots. */
export function playTreeBreeze(root: SVGGElement, delay = 180) {
  return decorativePlayback(root, motion => {
    const leaves = [...root.querySelectorAll<SVGElement>('[data-growth-leaf]')]
    const twigs = [...root.querySelectorAll<SVGElement>('[data-growth-note][data-breeze-origin]')]
    if (!leaves.length) return
    root.dataset.treeBreeze = 'true'
    motion.cleanup(() => { delete root.dataset.treeBreeze })
    const sway = (element: SVGElement, origin: string, angle: number, start: number) => {
      const style = element.getAttribute('style')
      element.dataset.breezeActive = 'true'
      element.style.transformOrigin = origin
      motion.cleanup(() => {
        delete element.dataset.breezeActive
        if (style === null) element.removeAttribute('style'); else element.setAttribute('style', style)
      })
      motion.animate(element, [
        { transform: 'rotate(0deg)' },
        { transform: `rotate(${angle}deg)`, offset: .22 },
        { transform: `rotate(${-angle * .65}deg)`, offset: .5 },
        { transform: `rotate(${angle * .36}deg)`, offset: .74 },
        { transform: `rotate(${-angle * .12}deg)`, offset: .9 },
        { transform: 'rotate(0deg)' },
      ], { delay: start, duration: 4600 })
    }
    // All visible home leaves participate, with a cap for unusually dense crowns.
    const count = Math.min(18, leaves.length)
    for (let i = 0; i < count; i++) {
      const leaf = leaves[Math.round(i * (leaves.length - 1) / Math.max(1, count - 1))]
      const start = delay + i * 55 + i % 2 * 35
      sway(leaf, '0px 3px', 15 + i % 3 * 2, start)
      const twig = twigs.find(t => t.dataset.growthBook === leaf.dataset.growthBook
        && JSON.stringify([t.dataset.growthBook, t.dataset.growthNote]) === leaf.dataset.growthLeaf)
      if (twig) sway(twig, twig.dataset.breezeOrigin!, 2.6 + i % 2 * .4, start + 110)
    }
  })
}
