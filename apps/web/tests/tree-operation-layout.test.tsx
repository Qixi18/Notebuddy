import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { WatercolorTree } from '../src/features/tree/WatercolorTree'
import { TreeVines } from '../src/features/tree/TreeVines'
import { notebookGeometry, sceneInitialCamera } from '../src/features/tree/treeGeometry'
import type { NotebookRead, SectionRead } from '../src/types'
import type { CrossCourseRelation, ForestCourse } from '../src/features/forest/types'

afterEach(cleanup)
const course: ForestCourse = { course_id: 'course', name: '离散数学', semester: 1, level: 'foundation', learning_state: 'learning', position: 0, revision: 1, note_count: 200, material_count: 1, prerequisites: [] }
const section = (bookId: string, slot: number): SectionRead => ({ id: `${bookId}-note-${slot}`, notebook_id: bookId, tree_slot: slot, knowledge_node_id: `node-${slot}`, material_id: 'chapter', section_key: String(slot), section_order: slot, title: `${bookId}第${slot}个很长的中文知识点标题用于确认标签准确命中`, revision_number: 1, user_locked: false, updated_at: '' })
const book = (slot: number, count = 7): NotebookRead => ({ id: `book-${slot}`, course_id: 'course', title: `第${slot}本数学笔记`, tree_slot: slot, order_revision: 0, chapters: [{ id: 'chapter', title: '第一讲', chapter_order: 0, status: 'completed', deleted_at: null, sections: Array.from({ length: count }, (_, index) => section(`book-${slot}`, index)) }], historical_sections: [], removed_chapters: [] })
const relation: CrossCourseRelation = { id: 'vine', source_course_id: 'course', target_course_id: 'other', source_note_id: 'from', target_note_id: 'to', source_title: '源知识点', target_title: '目标知识点', source_course_name: '甲', target_course_name: '乙', relation_type: 'related', reason: '证据', status: 'confirmed', origin: 'ai', source_revision: 1, target_revision: 1, stale: false, source_ref_ids: [], target_ref_ids: [] }
function tree(zoom: number, count = 7, onNote = vi.fn()) {
  return render(<svg><g transform={`translate(47,91) scale(${zoom})`}><WatercolorTree tree={{ course, x: 0, y: 0, seed: 1 }} branches={Array.from({ length: count }, (_, slot) => notebookGeometry(book(slot)))} zoom={zoom} pins={new Set()} growingNotes={new Set()} search="" onRoot={vi.fn()} onNotebook={vi.fn()} onNote={onNote} onExpand={vi.fn()} onExpandBooks={vi.fn()} onFocus={vi.fn()} onReveal={vi.fn()} /></g></svg>)
}
function screenRect(element: Element) {
  let x = Number(element.getAttribute('x')), y = Number(element.getAttribute('y'))
  let width = Number(element.getAttribute('width')), height = Number(element.getAttribute('height'))
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const operations = Array.from((parent.getAttribute('transform') ?? '').matchAll(/(translate|scale)\(([^)]+)\)/g)).reverse()
    for (const [, type, values] of operations) {
      const [first, second] = values.split(/[,\s]+/).map(Number)
      if (type === 'translate') { x += first; y += second ?? 0 }
      else { x *= first; y *= second ?? first; width *= first; height *= second ?? first }
    }
  }
  return { x, y, width, height }
}
const overlap = (a: ReturnType<typeof screenRect>, b: ReturnType<typeof screenRect>) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
function screenCircle(element: Element) {
  let x = Number(element.getAttribute('cx')), y = Number(element.getAttribute('cy')), radius = Number(element.getAttribute('r'))
  for (let parent = element.parentElement; parent; parent = parent.parentElement) for (const [, type, values] of Array.from((parent.getAttribute('transform') ?? '').matchAll(/(translate|scale)\(([^)]+)\)/g)).reverse()) {
    const [first, second] = values.split(/[,\s]+/).map(Number)
    if (type === 'translate') { x += first; y += second ?? 0 }
    else { x *= first; y *= second ?? first; radius *= first }
  }
  return { x, y, radius }
}
describe('screen operation dimensions', () => {
  it.each([.8, sceneInitialCamera(2, 390, 720).k])('separates all book-name and directory hit rectangles at zoom %s including SVG transforms', zoom => {
    const { container } = tree(zoom, 6)
    const controls = Array.from(container.querySelectorAll('.kt-book-hit, .kt-aggregate-hit'))
    expect(controls).toHaveLength(12)
    const rects = controls.map(screenRect)
    for (const rect of rects) {
      expect(rect.height).toBeGreaterThanOrEqual(44 - 1e-8)
      expect(rect.width).toBeGreaterThanOrEqual(44 - 1e-8)
    }
    for (let a = 0; a < rects.length; a++) for (let b = a + 1; b < rects.length; b++) expect(overlap(rects[a], rects[b])).toBe(false)
    for (const target of Array.from(container.querySelectorAll('.kt-leaf-hit'))) for (const rect of rects) expect(overlap(screenRect(target), rect)).toBe(false)
    for (const target of Array.from(container.querySelectorAll('.kt-leaf-icon-hit'))) for (const rect of rects) {
      const circle = screenCircle(target)
      const nearestX = Math.max(rect.x, Math.min(circle.x, rect.x + rect.width)), nearestY = Math.max(rect.y, Math.min(circle.y, rect.y + rect.height))
      expect(Math.hypot(circle.x - nearestX, circle.y - nearestY)).toBeGreaterThanOrEqual(circle.radius - 1e-8)
    }
  })
  it.each([[1100, 750], [390, 720]])('keeps notebook and course aggregate hits at 44px for %s×%s', (width, height) => {
    const zoom = sceneInitialCamera(2, width, height).k
    tree(zoom)
    for (const label of ['展开第0本数学笔记的全部7个知识点', '展开离散数学的全部7本笔记本']) {
      const button = screen.getByRole('button', { name: label })
      const rects = Array.from(button.querySelectorAll('rect'))
      expect(Math.max(...rects.map(rect => Number(rect.getAttribute('height')))) * zoom).toBeGreaterThanOrEqual(44 - 1e-8)
      expect(Math.max(...rects.map(rect => Number(rect.getAttribute('width')))) * zoom).toBeGreaterThanOrEqual(44 - 1e-8)
    }
    const titleHit = screen.getByRole('button', { name: '续读笔记本：第0本数学笔记' }).querySelector('.kt-book-hit')!
    expect(Number(titleHit.getAttribute('height')) * zoom).toBeGreaterThanOrEqual(44 - 1e-8)
  })
  it('keeps the relation hit stroke at 44 screen pixels below 100% zoom', () => {
    const zoom = sceneInitialCamera(2, 390, 720).k
    render(<svg><TreeVines relations={[relation]} endpoints={new Map([['from', { x: 0, y: 0 }], ['to', { x: 300, y: 0 }]])} zoom={zoom} onRelation={vi.fn()} /></svg>)
    const hit = screen.getByRole('button', { name: '查看甲与乙的1条知识联系' }).querySelector('path[stroke="transparent"]')!
    expect(Number(hit.getAttribute('stroke-width')) * zoom).toBeGreaterThanOrEqual(44 - 1e-8)
  })
  it('does not leave microscopic detail controls or giant inverse hits in low zoom overview', () => {
    const { container } = tree(.15)
    expect(screen.queryAllByRole('button', { name: /展开|打开知识点|续读笔记本/ })).toHaveLength(0)
    expect(container.querySelector('path[stroke-width="293.33333333333337"]')).toBeNull()
  })
})
describe('cross-branch label operation layout', () => {
  it('keeps long three-book labels and their hit rectangles apart while exact leaves remain anchored', () => {
    const onNote = vi.fn()
    const zoom = .8
    const { container } = tree(zoom, 3, onNote)
    const buttons = Array.from(container.querySelectorAll('.kt-note'))
    const bounds = (element: Element) => ({ x: Number(element.getAttribute('x')), y: Number(element.getAttribute('y')), width: Number(element.getAttribute('width')), height: Number(element.getAttribute('height')) })
    const intersects = (a: ReturnType<typeof bounds>, b: ReturnType<typeof bounds>) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
    for (let first = 0; first < buttons.length; first++) for (let second = first + 1; second < buttons.length; second++) {
      for (const selector of ['.kt-note-label-bg', '.kt-leaf-hit']) {
        const a = buttons[first].querySelector(selector), b = buttons[second].querySelector(selector)
        if (a && b) expect(intersects(bounds(a), bounds(b))).toBe(false)
      }
    }
    for (let first = 0; first < buttons.length; first++) for (let second = 0; second < buttons.length; second++) {
      if (first === second) continue
      const icon = buttons[first].querySelector('circle')!
      const target = bounds(buttons[second].querySelector('.kt-leaf-hit')!)
      const x = Number(icon.getAttribute('cx')), y = Number(icon.getAttribute('cy')), r = Number(icon.getAttribute('r'))
      expect(intersects({ x: x - r, y: y - r, width: r * 2, height: r * 2 }, target)).toBe(false)
    }
    for (let slot = 0; slot < 3; slot++) for (let index = 0; index < 6; index++) {
      const expected = section(`book-${slot}`, index)
      const button = screen.getByRole('button', { name: `打开知识点：${expected.title}` })
      fireEvent.click(button.querySelector('.kt-leaf-hit')!)
      expect(onNote).toHaveBeenLastCalledWith(expect.objectContaining({ id: `book-${slot}` }), expected)
      fireEvent.click(button.querySelector('.kt-leaf-icon-hit')!)
      expect(onNote).toHaveBeenLastCalledWith(expect.objectContaining({ id: `book-${slot}` }), expected)
      const paint = button.querySelector('[data-leaf-paint]')!
      const actual = notebookGeometry(book(slot)).leaves[index]
      expect(paint.getAttribute('transform')).toBe(`translate(${actual.x},${actual.y})`)
      const hit = bounds(button.querySelector('.kt-leaf-hit')!)
      expect(Math.abs(hit.y + hit.height / 2 - (actual.y - 30))).toBeLessThanOrEqual(125)
      expect(Math.abs(hit.x + hit.width / 2 - actual.x)).toBeLessThanOrEqual(200)
    }
  })
})
