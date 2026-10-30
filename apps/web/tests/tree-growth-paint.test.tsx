import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { playTreeGrowth } from '../src/features/tree/growth/paint'

beforeEach(() => {
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, writable: true, value: () => {} })
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: -40, y: -200, width: 100, height: 210 }) })
})
afterEach(() => { vi.restoreAllMocks(); delete (Element.prototype as Partial<Element>).animate; document.body.innerHTML = '' })
function fixture() {
  document.body.innerHTML = '<svg><g id="tree"><g data-growth-limb="book:primary" data-growth-book="book" data-growth-path="M0,0L0,-100" data-growth-radius="16" data-growth-level="1"><path d="M-10,0L0,-100L10,0Z"/></g><g data-note-id="note"><g data-leaf-paint="true" transform="translate(20,-100)"><g data-growth-leaf="note"><path d="M0,0L10,-20Z"/></g></g><ellipse data-home-leaf-id="note" cx="20" cy="-100" rx="22" ry="33"/></g></g></svg>'
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
  vi.spyOn(Element.prototype, 'animate').mockImplementation(() => { throw Error('unsupported SVG') })
  const p = playTreeGrowth(root, { course: false, books: new Set(['book']), notes: new Set() })
  await p.finished
  expect(root.querySelector('[mask]')).toBeNull()
  expect(root.querySelector('[data-growth-defs]')).toBeNull()
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
