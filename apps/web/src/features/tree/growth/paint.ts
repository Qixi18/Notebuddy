export type Playback = { finished: Promise<void>; finish: () => void }
export type TreeGrowth = { course: boolean; books: Set<string>; notes: Set<string> }
const SVG = 'http://www.w3.org/2000/svg'
let serial = 0
type Timing = { delay: number; duration: number }
const sectionKey = (bookId: string, blockId: string) => JSON.stringify([bookId, blockId])

/** Temporary masks affect paint only; every resource is removed on every exit. */
function painter(root: SVGGElement) {
  const effects: Animation[] = [], undo: (() => void)[] = []
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
    const effect = element.animate(frames, { ...timing, easing: 'cubic-bezier(.22,.61,.36,1)', fill: 'both' })
    effects.push(effect)
  }
  const mask = (element: SVGGraphicsElement, path: string, width: number, timing: Timing) => {
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
    animate(line, [{ strokeDashoffset: '1' }, { strokeDashoffset: '0' }], timing)
  }
  const leaf = (element: SVGElement, timing: Timing) => {
    const old = element.getAttribute('style')
    element.style.transformOrigin = element.dataset.growthOrigin ?? '0px 3px'
    undo.push(() => { if (old === null) element.removeAttribute('style'); else element.setAttribute('style', old) })
    animate(element, [{ opacity: 0, transform: 'scale(.12,.2)' }, { opacity: 1, transform: 'scale(1,1)' }], timing)
  }
  const run = (build: () => void): Playback => {
    try {
      build()
      if (!effects.length) finish()
      else {
        void Promise.all(effects.map(effect => effect.finished)).then(finish, finish)
        timer = setTimeout(finish, 1600)
      }
    } catch { finish() }
    return { finished, finish }
  }
  return { animate, mask, leaf, run }
}

export function playTreeGrowth(root: SVGGElement, growth: TreeGrowth): Playback {
  const paint = painter(root)
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
      const base = parent ? schedule(parent) : { delay: growth.course ? 300 : 0, duration: 0 }
      const level = Number(limb.dataset.growthLevel)
      const value = { delay: base.delay + base.duration * Number(limb.dataset.growthParentT ?? 1), duration: level === 0 ? 110 : level === 1 ? 440 : level === 2 ? 270 : 170 }
      timings.set(id, value); return value
    }
    for (const limb of selected) paint.mask(limb, limb.dataset.growthPath!, Number(limb.dataset.growthRadius) * 2 + 8, schedule(limb))
    let index = 0
    for (const element of root.querySelectorAll<SVGGElement>('[data-growth-leaf]')) {
      const id = element.dataset.growthLeaf!
      const bookId = element.dataset.growthBook!
      if (!growth.books.has(bookId) && !growth.notes.has(id)) continue
      const twigLimb = limbs.find(limb => limb.dataset.growthBook === bookId && limb.dataset.growthNote
        && sectionKey(bookId, limb.dataset.growthNote) === id)
      const twig = twigLimb ? timings.get(twigLimb.dataset.growthLimb!) : undefined
      paint.leaf(element, { delay: Math.min(1080, twig ? twig.delay + twig.duration - 20 : (growth.course ? 850 : 140) + index++ * 50), duration: 360 })
    }
    if (growth.course) {
      const trunk = root.querySelector<SVGGElement>('[data-growth-trunk]')
      if (trunk) {
        const bounds = trunk.getBBox()
        paint.mask(trunk, `M${bounds.x + bounds.width / 2},${bounds.y + bounds.height}V${bounds.y}`, bounds.width + 4, { delay: 0, duration: 420 })
      }
      for (const shadow of root.querySelectorAll<SVGElement>('[data-growth-shadow]')) paint.animate(shadow, [{ opacity: 0 }, { opacity: .14 }], { delay: 0, duration: 180 })
      for (const [i, bough] of [...root.querySelectorAll<SVGGraphicsElement>('[data-growth-sapling-path]')].entries()) paint.mask(bough, bough.dataset.growthSaplingPath!, 28, { delay: 360 + i * 30, duration: 420 })
      for (const [i, foliage] of [...root.querySelectorAll<SVGElement>('[data-growth-sapling-foliage]')].entries()) paint.animate(foliage, [{ opacity: 0 }, { opacity: 1 }], { delay: 770 + i * 30, duration: 300 })
    }
  })
}

export function playVineGrowth(root: SVGGElement, ids: Set<string>, stems: Set<string>): Playback {
  const paint = painter(root)
  return paint.run(() => {
    for (const element of root.querySelectorAll<SVGGElement>('[data-growth-vine-path]')) if (stems.has(element.dataset.growthVineGroup!)) paint.mask(element, element.dataset.growthVinePath!, 96, { delay: 0, duration: 760 })
    let index = 0
    for (const element of root.querySelectorAll<SVGGElement>('[data-growth-relation-leaf]')) {
      if (ids.has(element.dataset.growthRelationLeaf!)) paint.leaf(element, { delay: (stems.has(element.dataset.growthVineGroup!) ? 650 : 0) + Math.min(200, index++ * 45), duration: 300 })
    }
  })
}
