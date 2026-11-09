import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { HomeCourseTree } from '../src/features/home/HomeCourseTree'
import { TreeVines } from '../src/features/tree/TreeVines'
import { growthLedger } from '../src/features/tree/growth/ledger'
import type { NotebookRead } from '../src/types'
import type { TreeRelation } from '../src/features/forest/types'

const book = { id: 'breeze-book', course_id: 'breeze-course', title: '图论', tree_slot: 0, chapters: [{ id: 'chapter', title: '图', sections: Array.from({ length: 6 }, (_, i) => ({ id: `row-${i}`, block_id: `block-${i}`, notebook_id: 'breeze-book', tree_slot: i, title: `知识${i}` })) }], historical_sections: [] } as unknown as NotebookRead
const actions = { onPreview: vi.fn(), onLeave: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn() }
const home = (growth?: { courses: Set<string>; books: Set<string>; sections: Set<string> }) => <HomeCourseTree courseId="breeze-course" books={[book]} previewId="preview" growth={growth} {...actions} />
const row = (id = 'flow-relation'): TreeRelation => ({ id, source_course_id: 'right-course', target_course_id: 'left-course', source_notebook_id: 'right-book', target_notebook_id: 'left-book', source_block_id: 'right-note', target_block_id: 'left-note', source_title: '来源', target_title: '目标', source_course_name: '右侧课程', target_course_name: '左侧课程', status: 'confirmed', stale: false, origin: 'manual', relation_type: 'related', reason: '联系', created_at: '' }) as TreeRelation
const endpoints = new Map([['right-note', { x: 680, y: 120 }], ['left-note', { x: 20, y: 100 }]])
const records: { element: Element; frames: Keyframe[]; options: KeyframeAnimationOptions; complete: () => void }[] = []
let reduced = false
const mediaListeners = new Set<() => void>()
beforeEach(() => {
  sessionStorage.clear(); records.length = 0; reduced = false; mediaListeners.clear()
  vi.stubGlobal('matchMedia', () => ({ get matches() { return reduced }, addEventListener: (_: string, fn: () => void) => mediaListeners.add(fn), removeEventListener: (_: string, fn: () => void) => mediaListeners.delete(fn) }))
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, toJSON() {} })
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: -300, y: -700, width: 700, height: 730 }) })
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, writable: true, value: function (this: Element, frames: Keyframe[], options: KeyframeAnimationOptions) {
    let complete!: () => void
    const finished = new Promise<void>(resolve => { complete = resolve })
    records.push({ element: this, frames, options, complete }); return { finished, cancel: vi.fn() }
  } })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); delete (Element.prototype as Partial<Element>).animate; sessionStorage.clear() })

test('home entry survives StrictMode and breezes only leaf paint and twigs while targets stay fixed', async () => {
  const view = render(<StrictMode>{home()}</StrictMode>)
  await waitFor(() => expect(view.container.querySelector('[data-tree-breeze]')).not.toBeNull())
  const moving = view.container.querySelectorAll('[data-breeze-active]')
  expect(moving.length).toBeGreaterThan(1)
  expect(view.container.querySelectorAll('[data-growth-leaf][data-breeze-active]')).toHaveLength(6)
  for (const hit of view.container.querySelectorAll('[data-home-leaf-id]')) expect(hit.closest('[data-breeze-active]')).toBeNull()
  expect(view.container.querySelector('[data-growth-trunk] [style]')).toBeNull()
  fireEvent.focus(screen.getByRole('button', { name: '打开知识点：知识0' }))
  expect(view.container.querySelector('[data-tree-breeze], [data-breeze-active]')).toBeNull()
  const played = records.length
  view.rerender(<StrictMode>{home()}</StrictMode>)
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(records).toHaveLength(played)
})

test('new branch growth takes priority over the entry breeze', async () => {
  const view = render(home({ courses: new Set(), books: new Set([book.id]), sections: new Set() }))
  await waitFor(() => expect(view.container.querySelector('[data-growth-defs]')).not.toBeNull())
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(view.container.querySelector('[data-tree-breeze]')).toBeNull()
})

test('switching to reduced motion removes the entry breeze and restores leaf paint', async () => {
  const view = render(home())
  await waitFor(() => expect(view.container.querySelector('[data-tree-breeze]')).not.toBeNull())
  act(() => { reduced = true; for (const change of [...mediaListeners]) change() })
  expect(view.container.querySelector('[data-tree-breeze], [data-breeze-active]')).toBeNull()
  expect(view.container.querySelector('[data-growth-leaf][style]')).toBeNull()
})

test('two beams leave opposite ends together and meet at the center without blocking relation controls', () => {
  const onRelation = vi.fn()
  const view = render(<svg><TreeVines relations={[row()]} endpoints={endpoints} zoom={1} onRelation={onRelation} /></svg>)
  const stem = view.container.querySelector('[data-vine-id]')!
  fireEvent.pointerEnter(stem, { pointerType: 'mouse' })
  const flow = view.container.querySelector('[data-vine-flow]')!
  expect(flow).not.toBeNull()
  expect(flow.getAttribute('pointer-events')).toBe('none')
  expect(flow.getAttribute('aria-hidden')).toBe('true')
  const packets = flow.querySelectorAll('[data-flow-packet]')
  expect(packets).toHaveLength(2)
  const motion = records.find(record => record.element === packets[0])!
  const opposite = records.find(record => record.element === packets[1])!
  expect(motion.frames[0].offsetDistance).toBe('100%')
  expect(opposite.frames[0].offsetDistance).toBe('0%')
  expect(motion.frames.at(-1)!.offsetDistance).toBe('50%')
  expect(opposite.frames.at(-1)!.offsetDistance).toBe('50%')
  expect(motion.options.delay).toBe(opposite.options.delay)
  expect(motion.options.duration).toBe(opposite.options.duration)
  expect(flow.querySelectorAll('[data-flow-trail]').length).toBeGreaterThan(1)
  const bloom = flow.querySelector('[data-flow-bloom]')!
  expect(bloom).not.toBeNull()
  expect(Number(records.find(record => record.element === bloom)!.options.delay)).toBeGreaterThanOrEqual(Number(motion.options.duration) - 100)
  expect(flow.querySelector('[data-flow-source]')!.getAttribute('cx')).toBe('680')
  expect(flow.querySelector('[data-flow-target]')!.getAttribute('cx')).toBe('20')
  fireEvent.focus(screen.getByRole('button', { name: /查看来源与目标的手动关联/ }))
  expect(view.container.querySelectorAll('[data-vine-flow]')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: /查看来源与目标的手动关联/ }))
  expect(onRelation).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: 'flow-relation' }))
  view.unmount()
  expect(document.querySelector('[data-vine-flow], [data-flow-defs]')).toBeNull()
})

test('new vines and their guiding lights grow together from two ends on the same clock', async () => {
  growthLedger.observeRelations([])
  const scene = (rows: TreeRelation[]) => <svg><TreeVines relations={rows} endpoints={endpoints} zoom={1} onRelation={vi.fn()} /></svg>
  const view = render(scene([]))
  growthLedger.observeRelations([row()])
  view.rerender(scene([row()]))
  await waitFor(() => expect(view.container.querySelector('[data-growth-vine-path][mask]')).not.toBeNull())
  const fronts = [...view.container.querySelectorAll('mask [data-growth-front]')]
  expect(fronts).toHaveLength(2)
  const packets = [...view.container.querySelectorAll('[data-flow-packet]')]
  expect(packets).toHaveLength(2)
  const phase = (element: Element) => records.find(record => record.element === element)!
  expect(phase(fronts[0]).frames.at(-1)!.strokeDashoffset).toBe('.5')
  expect(phase(fronts[1]).frames.at(-1)!.strokeDashoffset).toBe('-.5')
  for (const element of [...fronts, ...packets]) {
    expect(phase(element).options).toMatchObject({ delay: 0, duration: 2400, easing: 'linear' })
  }
  const leaf = view.container.querySelector('[data-growth-relation-leaf]')!
  expect(Number(phase(leaf).options.delay)).toBeGreaterThan(0)
  expect(Number(phase(leaf).options.delay)).toBeLessThan(2581)
  act(() => { reduced = true; for (const change of [...mediaListeners]) change() })
  expect(view.container.querySelector('[data-vine-flow], [data-flow-defs]')).toBeNull()
})

test('a visible new stem still grows when its relation leaf is folded out of the view', async () => {
  growthLedger.observeRelations([])
  const exclusions = [{ center: { x: 350, y: 100 }, radius: 2000 }]
  const scene = (rows: TreeRelation[]) => <svg><TreeVines relations={rows} endpoints={endpoints} leafExclusions={exclusions} zoom={1} onRelation={vi.fn()} /></svg>
  const view = render(scene([]))
  growthLedger.observeRelations([row()])
  view.rerender(scene([row()]))
  expect(view.container.querySelector('[data-relation-id]')).toBeNull()
  await waitFor(() => expect(view.container.querySelectorAll('[data-growth-front]')).toHaveLength(2))
  expect(view.container.querySelectorAll('[data-flow-packet]')).toHaveLength(2)
  expect(growthLedger.pending()).toEqual([])
})

test('a relation pending at mount survives StrictMode with light and growth still simultaneous', async () => {
  growthLedger.observeRelations([])
  growthLedger.observeRelations([row()])
  const view = render(<StrictMode><svg><TreeVines relations={[row()]} endpoints={endpoints} zoom={1} onRelation={vi.fn()} /></svg></StrictMode>)
  await waitFor(() => expect(view.container.querySelector('[data-growth-vine-path][mask]')).not.toBeNull())
  await waitFor(() => expect(view.container.querySelector('[data-vine-flow]')).not.toBeNull())
  expect(growthLedger.pending()).toEqual([])
})

test('adding a leaf to a baseline vine preserves the old stem and its existing leaf', async () => {
  const baseline = row('baseline'), added = row('added-leaf')
  const scene = (rows: TreeRelation[]) => <svg><TreeVines relations={rows} endpoints={endpoints} zoom={1} onRelation={vi.fn()} /></svg>
  growthLedger.observeRelations([baseline])
  const view = render(scene([baseline]))
  await act(async () => { await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))) })
  growthLedger.observeRelations([baseline, added])
  view.rerender(scene([baseline, added]))
  await waitFor(() => expect(view.container.querySelector('[data-growth-relation-leaf="added-leaf"][style]')).not.toBeNull())
  expect(view.container.querySelector('[data-growth-vine-path][mask]')).toBeNull()
  expect(view.container.querySelector('[data-growth-relation-leaf="baseline"][style]')).toBeNull()
  expect(view.container.querySelector('[data-growth-relation-petiole="baseline"][style]')).toBeNull()
})

test('equivalent directory refreshes keep in-flight growth and its guiding light', async () => {
  growthLedger.observeRelations([])
  const scene = (rows: TreeRelation[]) => <svg><TreeVines relations={rows} endpoints={new Map(endpoints)} zoom={1} onRelation={vi.fn()} /></svg>
  const view = render(scene([]))
  growthLedger.observeRelations([row()])
  view.rerender(scene([row()]))
  await waitFor(() => expect(view.container.querySelector('[data-growth-vine-path][mask]')).not.toBeNull())
  view.rerender(scene([{ ...row() }]))
  expect(view.container.querySelector('[data-growth-vine-path][mask]')).not.toBeNull()
  await waitFor(() => expect(view.container.querySelector('[data-vine-flow]')).not.toBeNull())
})

test('hovering one of two autoplaying groups keeps only the requested flow', async () => {
  const second = { ...row('flow-second'), source_course_id: 'right-two', target_course_id: 'left-two', source_block_id: 'right-two-note', target_block_id: 'left-two-note' }
  const points = new Map([...endpoints, ['right-two-note', { x: 680, y: 320 }], ['left-two-note', { x: 20, y: 300 }]])
  const scene = (rows: TreeRelation[]) => <svg><TreeVines relations={rows} endpoints={points} zoom={1} onRelation={vi.fn()} /></svg>
  growthLedger.observeRelations([])
  const view = render(scene([]))
  growthLedger.observeRelations([row(), second])
  view.rerender(scene([row(), second]))
  await waitFor(() => expect(view.container.querySelectorAll('[data-growth-vine-path][mask]')).toHaveLength(2))
  await waitFor(() => expect(view.container.querySelectorAll('[data-vine-flow]')).toHaveLength(2))
  fireEvent.pointerEnter(view.container.querySelector('[data-vine-members="flow-relation"]')!, { pointerType: 'mouse' })
  expect(view.container.querySelectorAll('[data-vine-flow]')).toHaveLength(1)
  expect(view.container.querySelector('[data-vine-flow]')!.getAttribute('data-vine-flow')).toBe('flow-relation')
})

test('reduced-motion users get static vines and fully operable relation controls', () => {
  reduced = true
  const onRelation = vi.fn()
  const view = render(<svg><TreeVines relations={[row()]} endpoints={endpoints} zoom={1} onRelation={onRelation} /></svg>)
  fireEvent.pointerEnter(view.container.querySelector('[data-vine-id]')!, { pointerType: 'mouse' })
  const leaf = screen.getByRole('button', { name: /查看来源与目标的手动关联/ })
  fireEvent.focus(leaf); fireEvent.keyDown(leaf, { key: 'Enter' })
  expect(view.container.querySelector('[data-vine-flow]')).toBeNull()
  expect(onRelation).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: 'flow-relation' }))
})

test('a real endpoint move clears flow painted for the previous vine geometry', () => {
  const rows = [row()]
  const scene = (points: typeof endpoints) => <svg><TreeVines relations={rows} endpoints={points} zoom={1} onRelation={vi.fn()} /></svg>
  const view = render(scene(endpoints))
  fireEvent.pointerEnter(view.container.querySelector('[data-vine-id]')!, { pointerType: 'mouse' })
  expect(view.container.querySelector('[data-vine-flow]')).not.toBeNull()
  view.rerender(scene(new Map([['right-note', { x: 750, y: 200 }], ['left-note', { x: 20, y: 100 }]])))
  expect(view.container.querySelector('[data-vine-flow], [data-flow-defs]')).toBeNull()
})
