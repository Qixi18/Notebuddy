import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { playTreeGrowth, playVineGrowth } from '../src/features/tree/growth/paint'
import type { VineGeometry } from '../src/features/tree/vineGeometry'
import { TREE_GROWTH_LIFETIME_MS } from '../src/features/tree/growth/timing'

beforeEach(() => {
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, writable: true, value: () => {} })
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: -40, y: -200, width: 100, height: 210 }) })
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete (Element.prototype as Partial<Element>).animate; document.body.innerHTML = '' })
function fixture() {
  document.body.innerHTML = '<svg><g id="tree"><g data-growth-limb="book:primary" data-growth-book="book" data-growth-path="M0,0L0,-100" data-growth-radius="16" data-growth-level="1"><path d="M-10,0L0,-100L10,0Z"/></g><g data-note-id="note"><g data-leaf-paint="true" transform="translate(20,-100)"><g data-growth-leaf="note" data-growth-book="book"><path d="M0,0L10,-20Z"/></g></g><ellipse data-home-leaf-id="note" cx="20" cy="-100" rx="22" ry="33"/></g></g></svg>'
  return document.getElementById('tree') as unknown as SVGGElement
}
test('growth masks original paint and never transforms leaf hit targets; interruption removes all effects', () => {
  const root = fixture()
  const hit = root.querySelector('ellipse')!.outerHTML
  const shape = root.querySelector('[data-growth-limb] > path')!.getAttribute('d')
  const effects: { cancel: ReturnType<typeof vi.fn> }[] = []
  vi.spyOn(Element.prototype, 'animate').mockImplementation(() => {
    const a = { finished: new Promise<Animation>(() => {}), cancel: vi.fn() }; effects.push(a); return a as unknown as Animation
  })
  const playback = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set(['note']) })
  expect(root.querySelector('[data-growth-limb]')!.getAttribute('mask')).toContain('url(')
  expect(root.querySelector('mask [stroke-dasharray]')).not.toBeNull()
  expect(root.querySelector('ellipse')!.outerHTML).toBe(hit)
  expect(root.querySelector('[data-growth-limb] > path')!.getAttribute('d')).toBe(shape)
  playback.finish()
  expect(root.querySelector('[data-growth-limb]')!.hasAttribute('mask')).toBe(false)
  expect(root.querySelector('[data-growth-defs]')).toBeNull()
  expect(root.querySelector('ellipse')!.outerHTML).toBe(hit)
  expect(effects.every(a => a.cancel.mock.calls.length === 1)).toBe(true)
})
test('partial native animation failure falls back to intact original paint', async () => {
  const root = fixture()
  let calls = 0
  vi.spyOn(Element.prototype, 'animate').mockImplementation(() => {
    if (++calls === 3) throw Error('unsupported SVG')
    return { finished: new Promise<Animation>(() => {}), cancel: vi.fn() } as unknown as Animation
  })
  const p = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set() })
  await p.finished
  expect(root.querySelector('[mask]')).toBeNull()
  expect(root.querySelector('[data-growth-defs]')).toBeNull()
  expect(root.querySelector('[data-growth-light], [data-growth-light-defs]')).toBeNull()
  expect(root.querySelector('[data-home-leaf-id]')).not.toBeNull()
})
test('completed native effects remove masks instead of retaining a clipped final frame', async () => {
  const root = fixture()
  vi.spyOn(Element.prototype, 'animate').mockImplementation(() => ({ finished: Promise.resolve(), cancel: vi.fn() }) as unknown as Animation)
  const p = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set(['note']) })
  await p.finished
  expect(root.querySelector('[mask]')).toBeNull()
  expect(root.querySelector('[data-growth-defs]')).toBeNull()
})

test('slower tree playback scales every phase and keeps masks past the original cleanup deadline', async () => {
  vi.useFakeTimers()
  const root = fixture()
  const timings: KeyframeAnimationOptions[] = []
  vi.spyOn(Element.prototype, 'animate').mockImplementation((_frames, options) => {
    timings.push(options as KeyframeAnimationOptions)
    return { finished: new Promise<Animation>(() => {}), cancel: vi.fn() } as unknown as Animation
  })
  const playback = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set(['note']) }, 1.4)
  expect(Number(timings[0].duration)).toBeGreaterThan(1400)
  expect(timings.every(t => Number(t.delay) + Number(t.duration) <= TREE_GROWTH_LIFETIME_MS * 1.4)).toBe(true)
  vi.advanceTimersByTime(1600)
  expect(root.querySelector('[mask]')).not.toBeNull()
  vi.advanceTimersByTime(TREE_GROWTH_LIFETIME_MS * 1.4 - 1600)
  await playback.finished
  expect(root.querySelector('[mask]')).toBeNull()
  expect(root.querySelector('[data-growth-defs]')).toBeNull()
})

test('default tree playback gives a main branch time to be noticed', () => {
  const root = fixture()
  const animate = vi.spyOn(Element.prototype, 'animate').mockImplementation(() => ({ finished: new Promise<Animation>(() => {}), cancel: vi.fn() }) as unknown as Animation)
  const playback = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set() })
  expect(Number((animate.mock.calls[0][1] as KeyframeAnimationOptions).duration)).toBeGreaterThanOrEqual(1200)
  playback.finish()
})

test('vine petioles and leaves wait until the guiding front reaches their attachment', () => {
  document.body.innerHTML = '<svg><g id="vine"><g data-growth-vine-group="v" data-growth-vine-path="M0,0L600,0"><path d="M0,0L600,0"/></g><path data-growth-relation-petiole="near" data-growth-vine-group="v" d="M60,0L60,-20"/><g data-growth-relation-leaf="near" data-growth-vine-group="v" data-growth-vine-t=".1"/><path data-growth-relation-petiole="middle" data-growth-vine-group="v" d="M300,0L300,-20"/><g data-growth-relation-leaf="middle" data-growth-vine-group="v" data-growth-vine-t=".5"/></g></svg>'
  const root = document.getElementById('vine') as unknown as SVGGElement
  const vine: VineGeometry = { id: 'v', order: 0, curves: [[{ x: 0, y: 0 }, { x: 200, y: 0 }, { x: 400, y: 0 }, { x: 600, y: 0 }]], centerline: 'M0,0L600,0', outline: '', grain: [], tendrils: [], leaves: [], hit: { centerline: '', minScreenWidth: 44, fromT: 0, toT: 1 } }
  const animate = vi.spyOn(Element.prototype, 'animate').mockImplementation(() => ({ finished: new Promise<Animation>(() => {}), cancel: vi.fn() }) as unknown as Animation)
  const playback = playVineGrowth(root, new Set(['near', 'middle']), new Set(['v']), [{ vine, relationId: 'near', options: { reverse: false, screenScale: 1 } }])
  const phase = (selector: string) => animate.mock.calls[animate.mock.instances.indexOf(root.querySelector(selector)!)][1] as KeyframeAnimationOptions
  expect(Number(phase('[data-growth-relation-petiole="near"]').delay)).toBe(480)
  expect(Number(phase('[data-growth-relation-leaf="near"]').delay)).toBe(660)
  expect(Number(phase('[data-growth-relation-petiole="middle"]').delay)).toBe(2400)
  expect(Number(phase('[data-growth-relation-leaf="middle"]').delay)).toBe(2580)
  playback.finish()
  expect(root.querySelector('[mask], [data-vine-flow], [data-growth-defs]')).toBeNull()
})

test('growth lights follow the local branch path without moving hit targets and disappear on interruption', () => {
  const root = fixture()
  const limb = root.querySelector<SVGGElement>('[data-growth-limb]')!
  limb.setAttribute('transform', 'translate(30,-10)')
  const hit = root.querySelector('ellipse')!.outerHTML
  vi.spyOn(Element.prototype, 'animate').mockImplementation(() => ({ finished: new Promise<Animation>(() => {}), cancel: vi.fn() }) as unknown as Animation)
  const playback = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set() })
  const light = root.querySelector<SVGGElement>('[data-growth-light="path"]')!
  expect(light).not.toBeNull()
  expect(light.parentElement).toBe(limb.parentElement)
  expect(light.getAttribute('transform')).toBe('translate(30,-10)')
  expect(light.getAttribute('pointer-events')).toBe('none')
  expect(light.getAttribute('aria-hidden')).toBe('true')
  expect(light.querySelector<SVGElement>('[data-growth-tip]')!.style.offsetPath).toContain('M0,0L0,-100')
  expect(root.querySelector('ellipse')!.outerHTML).toBe(hit)
  playback.finish()
  expect(root.querySelector('[data-growth-light]')).toBeNull()
  expect(root.querySelector('[data-growth-light-defs]')).toBeNull()
})

test('a new course unfolds its leaves even without individual notebook receipts', () => {
  const root = fixture()
  const animate = vi.spyOn(Element.prototype, 'animate').mockImplementation(() => ({ finished: new Promise<Animation>(() => {}), cancel: vi.fn() }) as unknown as Animation)
  const playback = playTreeGrowth(root, { course: true, books: new Set(), notes: new Set() })
  expect(animate.mock.instances).toContain(root.querySelector('[data-growth-leaf]'))
  expect(root.querySelector('[data-growth-light="leaf"]')).not.toBeNull()
  playback.finish()
})

test('decorative growth lights stay bounded for a dense notebook', () => {
  const root = fixture()
  const limb = root.querySelector('[data-growth-limb]')!
  const leaf = root.querySelector('[data-growth-leaf]')!
  for (let i = 0; i < 60; i++) {
    const branch = limb.cloneNode(true) as SVGGElement
    branch.dataset.growthLimb = `branch-${i}`
    root.append(branch, leaf.cloneNode(true))
  }
  vi.spyOn(Element.prototype, 'animate').mockImplementation(() => ({ finished: new Promise<Animation>(() => {}), cancel: vi.fn() }) as unknown as Animation)
  const playback = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set() })
  expect(root.querySelectorAll('[data-growth-light="path"]').length).toBeGreaterThan(0)
  expect(root.querySelectorAll('[data-growth-light="path"]').length).toBeLessThanOrEqual(10)
  expect(root.querySelectorAll('[data-growth-light="leaf"]')).toHaveLength(12)
  playback.finish()
  expect(root.querySelector('[data-growth-light]')).toBeNull()
})
