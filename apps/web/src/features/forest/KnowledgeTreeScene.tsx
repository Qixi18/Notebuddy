import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { forestLayout, signature, TREE_SPACING, type SavedSlot, type TreePosition } from './layout'
import { useForestCamera } from './useForestCamera'
import { BOTANICAL_SPACING, fitPoints, notebookGeometry, overviewLeaves, overviewBranches, sceneInitialCamera, type Point } from './treeGeometry'
import { WatercolorTree } from './WatercolorTree'
import { TreeVines } from './TreeVines'
import { TreeContents, type TreeContentsSelection } from './TreeContents'
import type { KnowledgeTreeSceneProps } from './sceneTypes'
import { detailInteraction } from './treeInteraction'
import { placeLeafLabels } from './leafLabels'
import { projectNotebookControls } from './notebookControls'
import './knowledge-tree.css'

export type { KnowledgeTreeSceneProps, KnowledgeTreeView } from './sceneTypes'

export function KnowledgeTreeScene({ courses, trees, mode = 'forest', initialView, onViewChange, focusCourseId, onFocusCourse, search = '', pinnedNoteIds = [], relations = [], selectedRelationId, onVisibleCourseIdsChange, onRoot, onNotebook, onNote, onRelation, className = '' }: KnowledgeTreeSceneProps) {
  const host = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ width: initialView?.viewport.width ?? 1100, height: initialView?.viewport.height ?? 760, ready: false })
  const slots = useRef<Record<string, SavedSlot>>(initialView?.slots ?? {})
  const restored = useRef(initialView)
  const initialized = useRef(false)
  const contentFramed = useRef(Boolean(initialView))
  const firstCamera = useRef<{ x: number; y: number; k: number } | undefined>(undefined)
  const [selection, setSelection] = useState<TreeContentsSelection>()
  const [revealed, setRevealed] = useState(initialView?.revealedNoteId)
  const restoredContents = useRef(initialView?.contents)
  const contentsRestored = useRef(!initialView?.contents)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const initial = useRef(initialView?.camera ?? sceneInitialCamera(courses.length, viewport.width, viewport.height))
  const camera = useForestCamera(initial.current, viewport.width, viewport.height, viewport.ready, true)
  const positions = useMemo(() => {
    // Home preserves the caller's recency order. Forest preserves semester/manual
    // order and persisted world slots. Both use exactly the same tree geometry.
    const raw = mode === 'home'
      ? courses.map((course, index) => ({ course, x: 280 + index * TREE_SPACING, y: 790, seed: index }))
      : forestLayout(courses, slots.current)
    for (const tree of raw) slots.current[tree.course.course_id] = { x: tree.x, signature: signature(tree.course) }
    return raw.map(tree => ({ ...tree, x: (tree.x - 280) / TREE_SPACING * BOTANICAL_SPACING + BOTANICAL_SPACING / 2 }))
  }, [courses, mode])
  const treeMap = useMemo(() => new Map(trees.map(tree => [tree.course_id, tree])), [trees])
  const knownCourses = useRef(new Set<string>())
  const knownNotes = useRef(new Set<string>())
  const knownBooks = useRef(new Map(Object.entries(initialView?.knownNotebookIds ?? {})
    .filter(([, ids]) => Array.isArray(ids) && ids.every(id => typeof id === 'string'))
    .map(([id, ids]) => [id, new Set(ids)])))
  const growingBooks = useMemo(() => {
    const fresh = new Set<string>()
    const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    for (const tree of trees) {
      const previous = knownBooks.current.get(tree.course_id)
      if (previous && !reduced) for (const book of tree.notebooks) {
        if (book.course_id === tree.course_id && !previous.has(book.id)) fresh.add(book.id)
      }
    }
    return fresh
  }, [trees])
  const growingNotes = useMemo(() => {
    const fresh = new Set<string>()
    for (const tree of trees) for (const book of tree.notebooks) for (const section of [...book.chapters.flatMap(chapter => chapter.sections), ...book.historical_sections]) {
      if (knownCourses.current.has(tree.course_id) && !knownNotes.current.has(section.id)) fresh.add(section.id)
    }
    return fresh
  }, [trees])
  useEffect(() => {
    for (const tree of trees) {
      knownCourses.current.add(tree.course_id)
      const books = knownBooks.current.get(tree.course_id) ?? new Set<string>()
      for (const book of tree.notebooks) if (book.course_id === tree.course_id) books.add(book.id)
      knownBooks.current.set(tree.course_id, books)
      for (const book of tree.notebooks) for (const section of [...book.chapters.flatMap(chapter => chapter.sections), ...book.historical_sections]) knownNotes.current.add(section.id)
    }
  }, [trees])
  const branchMap = useMemo(() => new Map(trees.map(tree => [tree.course_id, tree.notebooks.filter(book => book.course_id === tree.course_id).sort((a, b) => a.tree_slot - b.tree_slot).map(notebookGeometry)])), [trees])
  useEffect(() => {
    if (contentsRestored.current || !restoredContents.current) return
    const saved = restoredContents.current
    const directory = treeMap.get(saved.courseId)
    const course = courses.find(course => course.course_id === saved.courseId)
    if (!directory || !course) return
    contentsRestored.current = true
    setSelection({ courseId: saved.courseId, courseName: course.name, books: directory.notebooks, notebookId: saved.notebookId && directory.notebooks.some(book => book.id === saved.notebookId) ? saved.notebookId : undefined, trigger: null })
  }, [treeMap, courses])
  const pins = useMemo(() => {
    const result = new Set(pinnedNoteIds)
    if (revealed) result.add(revealed)
    const selected = relations.find(relation => relation.id === selectedRelationId && relation.status === 'confirmed' && !relation.stale)
    if (selected) { result.add(selected.source_note_id); result.add(selected.target_note_id) }
    return result
  }, [pinnedNoteIds, revealed, relations, selectedRelationId])
  const endpoints = useMemo(() => {
    const result = new Map<string, Point>()
    for (const tree of positions) for (const branch of overviewBranches(branchMap.get(tree.course.course_id) ?? [], pins, search)) for (const leaf of overviewLeaves(branch, pins, search, selection?.notebookId === branch.book.id)) result.set(leaf.section.id, { x: tree.x + leaf.x, y: tree.y + leaf.y - 25 })
    return result
  }, [positions, branchMap, pins, search, selection?.notebookId])
  const selectedCourses = useMemo(() => {
    const selected = relations.find(relation => relation.id === selectedRelationId && relation.status === 'confirmed' && !relation.stale)
    return new Set(selected ? [selected.source_course_id, selected.target_course_id] : [])
  }, [relations, selectedRelationId])
  const visible = useMemo(() => {
    const left = -camera.camera.x / camera.camera.k - BOTANICAL_SPACING
    const right = (viewport.width - camera.camera.x) / camera.camera.k + BOTANICAL_SPACING
    return positions.filter(tree => tree.x + 300 >= left && tree.x - 300 <= right || selectedCourses.has(tree.course.course_id) || tree.course.course_id === focusCourseId || (branchMap.get(tree.course.course_id) ?? []).some(branch => branch.leaves.some(leaf => pins.has(leaf.section.id))))
  }, [positions, camera.camera.x, camera.camera.k, viewport.width, focusCourseId, branchMap, pins, selectedCourses])
  const visibleKey = visible.map(tree => tree.course.course_id).join('|')
  const visibleCallback = useRef(onVisibleCourseIdsChange)
  visibleCallback.current = onVisibleCourseIdsChange
  useEffect(() => { visibleCallback.current?.(visibleKey ? visibleKey.split('|') : []) }, [visibleKey])
  useEffect(() => {
    if (!host.current) return
    const measure = () => {
      const rect = host.current?.getBoundingClientRect()
      if (rect && rect.width > 0 && rect.height > 0) setViewport(previous => previous.width === rect.width && previous.height === rect.height && previous.ready ? previous : { width: rect.width, height: rect.height, ready: true })
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure)
    observer?.observe(host.current)
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  useEffect(() => {
    if (!viewport.ready || !courses.length) return
    const initialCourses = positions.slice(0, sceneInitialCamera(courses.length, viewport.width, viewport.height).visibleCount)
    const directoriesReady = initialCourses.every(tree => treeMap.has(tree.course.course_id))
    if (initialized.current) {
      if (contentFramed.current || !directoriesReady) return
      contentFramed.current = true
      const previous = firstCamera.current, current = camera.cameraRef.current
      // Lazy content gets one first frame only while the reader has left the
      // original camera untouched. Returning and user movement always win.
      if (!previous || previous.x !== current.x || previous.y !== current.y || previous.k !== current.k) return
    }
    initialized.current = true
    if (restored.current) {
      camera.move({ ...restored.current.camera, x: restored.current.camera.x + (viewport.width - restored.current.viewport.width) / 2, y: restored.current.camera.y + (viewport.height - restored.current.viewport.height) / 2 })
    } else {
      const initialFrame = sceneInitialCamera(courses.length, viewport.width, viewport.height)
      const points = positions.slice(0, initialFrame.visibleCount).flatMap(tree => {
        const branches = (branchMap.get(tree.course.course_id) ?? []).slice(0, 6)
        const items = branches.map(branch => ({ branch, leaves: overviewLeaves(branch, new Set(), '') }))
        const controls = projectNotebookControls(items, initialFrame.k)
        const labels = placeLeafLabels(items, initialFrame.k, controls)
        const rectangles = [...labels.map(label => label.rect), ...[...controls.values()].flatMap(control => [control.title, control.directory])]
        return [{ x: tree.x - 310, y: tree.y - 735 }, { x: tree.x + 310, y: tree.y + 65 }, ...rectangles.flatMap(rect => [{ x: tree.x + rect.x, y: tree.y + rect.y }, { x: tree.x + rect.x + rect.width, y: tree.y + rect.y + rect.height }])]
      })
      const frame = points.length ? fitPoints(points, viewport.width, viewport.height, 30) : initialFrame
      camera.move(frame)
      firstCamera.current = frame
      if (directoriesReady) contentFramed.current = true
    }
  }, [viewport, camera.move, courses.length, positions, branchMap, treeMap])
  const callback = useRef(onViewChange)
  callback.current = onViewChange
  const rememberView = () => {
    if (viewport.ready) callback.current?.({ camera: { ...camera.cameraRef.current }, viewport: { width: viewport.width, height: viewport.height }, slots: { ...slots.current }, focusedCourseId: focusCourseId,
      contents: selection ? { courseId: selection.courseId, notebookId: selection.notebookId } : !contentsRestored.current ? restoredContents.current : undefined,
      revealedNoteId: revealed,
      knownNotebookIds: Object.fromEntries([...knownBooks.current].map(([id, ids]) => [id, [...ids]])),
    })
  }
  useEffect(() => {
    rememberView()
  }, [camera.camera, viewport, focusCourseId, selection, revealed, trees])
  const focusTree = useCallback((tree: TreePosition) => {
    const branches = branchMap.get(tree.course.course_id) ?? []
    const items = branches.slice(0, 6).map(branch => ({ branch, leaves: overviewLeaves(branch, new Set(), '') }))
    const zoom = Math.max(.5, camera.cameraRef.current.k)
    const controls = projectNotebookControls(items, zoom)
    const labels = placeLeafLabels(items, zoom, controls)
    const rectangles = [...labels.map(label => label.rect), ...[...controls.values()].flatMap(control => [control.title, control.directory])]
    const points = [{ x: tree.x - 310, y: tree.y - 735 }, { x: tree.x + 310, y: tree.y + 65 }, ...branches.slice(0, 6).flatMap(branch => branch.leaves.slice(0, 6).map(leaf => ({ x: tree.x + leaf.x, y: tree.y + leaf.y - 65 }))), ...rectangles.flatMap(rect => [{ x: tree.x + rect.x, y: tree.y + rect.y }, { x: tree.x + rect.x + rect.width, y: tree.y + rect.y + rect.height }])]
    const framed = fitPoints(points, viewport.width, viewport.height, 30)
    // Course overview controls promise to enter an operable detail view. On a
    // short canvas preserve the root and let the user pan the upper canopy.
    camera.move(framed.k >= .5 ? framed : { k: .75, x: viewport.width / 2 - tree.x * .75, y: viewport.height * .82 - tree.y * .75 })
  }, [branchMap, camera.move, viewport.width, viewport.height])
  const previousFocus = useRef(initialView?.focusedCourseId)
  useEffect(() => {
    if (!focusCourseId) previousFocus.current = undefined
    if (focusCourseId && previousFocus.current !== focusCourseId) {
      const tree = positions.find(tree => tree.course.course_id === focusCourseId)
      if (tree && viewport.ready) { focusTree(tree); previousFocus.current = focusCourseId }
    }
  }, [focusCourseId, positions, viewport.ready, focusTree])
  // Ambient automatic vines can reveal a bounded set of leaves but must not
  // move a camera the reader is using. Only an explicit selection frames it.
  const focusPins = useMemo(() => {
    const ids = new Set<string>(revealed ? [revealed] : [])
    const selected = relations.find(relation => relation.id === selectedRelationId && relation.status === 'confirmed' && !relation.stale)
    if (selected) { ids.add(selected.source_note_id); ids.add(selected.target_note_id) }
    return ids
  }, [revealed, relations, selectedRelationId])
  const pinKey = [...focusPins].sort().join('|')
  const lastPinFocus = useRef(initialView ? pinKey : '')
  useEffect(() => {
    if (!viewport.ready || !pinKey || pinKey === lastPinFocus.current) return
    const points = [...focusPins].flatMap(id => endpoints.has(id) ? [endpoints.get(id)!] : [])
    // A selected relation can load its two directories separately. Do not mark
    // this pin set framed until every requested real endpoint is available.
    if (points.length !== focusPins.size) return
    camera.move(fitPoints(points, viewport.width, viewport.height, 100))
    lastPinFocus.current = pinKey
  }, [pinKey, focusPins, endpoints, viewport, camera.move])
  const closeContents = () => {
    const trigger = selection?.trigger
    contentsRestored.current = true
    setSelection(undefined)
    if (!revealed && (trigger instanceof SVGElement || trigger instanceof HTMLElement)) trigger.focus()
    else camera.svgRef.current?.focus()
  }
  const allBooks = (courseId: string) => treeMap.get(courseId)?.notebooks ?? []
  const openContents = (courseId: string, courseName: string, notebookId?: string) => setSelection({ courseId, courseName, books: allBooks(courseId), notebookId, trigger: document.activeElement })
  const pointVisible = (point: Point) => point.x * camera.cameraRef.current.k + camera.cameraRef.current.x > 48 && point.x * camera.cameraRef.current.k + camera.cameraRef.current.x < viewport.width - 48 && point.y * camera.cameraRef.current.k + camera.cameraRef.current.y > 72 && point.y * camera.cameraRef.current.k + camera.cameraRef.current.y < viewport.height - 48
  const fit = () => camera.move(fitPoints(positions.flatMap(tree => [{ x: tree.x - 280, y: tree.y - 735 }, { x: tree.x + 280, y: tree.y + 80 }]), viewport.width, viewport.height, 30))
  return <div ref={host} className={`knowledge-tree-scene ${className}`} data-scene-mode={mode}>
    <div className="kt-camera-controls" role="group" aria-label="知识树画布控制">
      <button aria-label="向左浏览课程" onClick={() => camera.pan(BOTANICAL_SPACING * camera.camera.k)}>‹</button>
      <button aria-label="缩小知识树" onClick={() => camera.scale(1 / 1.2)}>−</button>
      <output aria-label="知识树缩放">{Math.round(camera.camera.k * 100)}%</output>
      <button aria-label="放大知识树" onClick={() => camera.scale(1.2)}>+</button>
      <button aria-label="适应全部课程" onClick={fit}>适应</button>
      <button aria-label="向右浏览课程" onClick={() => camera.pan(-BOTANICAL_SPACING * camera.camera.k)}>›</button>
    </div>
    <svg ref={camera.svgRef} width="100%" height="100%" className="kt-canvas" aria-label="课程知识树，拖动画布或使用方向键浏览" tabIndex={0}
      onMouseDownCapture={event => { drag.current = { x: event.clientX, y: event.clientY, moved: false } }}
      onMouseMoveCapture={event => { if (drag.current && Math.hypot(event.clientX - drag.current.x, event.clientY - drag.current.y) > 6) drag.current.moved = true }}
      onTouchStartCapture={event => { const touch = event.touches[0]; if (touch) drag.current = { x: touch.clientX, y: touch.clientY, moved: false } }}
      onTouchMoveCapture={event => { const touch = event.touches[0]; if (touch && drag.current && Math.hypot(touch.clientX - drag.current.x, touch.clientY - drag.current.y) > 6) drag.current.moved = true }}
      onClickCapture={event => { if (drag.current?.moved) { event.preventDefault(); event.stopPropagation() }; drag.current = null }}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return
        const arrows: Record<string, [number, number]> = { ArrowLeft: [100, 0], ArrowRight: [-100, 0], ArrowUp: [0, 100], ArrowDown: [0, -100] }
        if (arrows[event.key]) { event.preventDefault(); camera.pan(...arrows[event.key]) }
        if (event.key === '+' || event.key === '=') camera.scale(1.2)
        if (event.key === '-') camera.scale(1 / 1.2)
        if (event.key === 'Escape') { setRevealed(undefined); fit() }
      }}>
      <g ref={camera.sceneRef}>
        <TreeVines relations={relations} endpoints={endpoints} zoom={camera.camera.k} selectedId={selectedRelationId} onRelation={relation => { rememberView(); onRelation(relation) }} />
        {visible.map(tree => <WatercolorTree key={tree.course.course_id} tree={tree} branches={branchMap.get(tree.course.course_id) ?? []} zoom={camera.camera.k} pins={pins} growingNotes={growingNotes} growingBooks={growingBooks} search={search} expandedBookId={selection?.notebookId}
          onRoot={() => { rememberView(); onRoot(tree.course.course_id) }} onNotebook={book => { rememberView(); onNotebook(tree.course.course_id, book.id) }} onNote={(book, section) => { rememberView(); onNote(tree.course.course_id, book.id, section) }}
          onExpand={book => openContents(tree.course.course_id, tree.course.name, book.id)} onExpandBooks={() => openContents(tree.course.course_id, tree.course.name)}
          onFocus={() => { onFocusCourse?.(tree.course.course_id); if (!pointVisible({ x: tree.x, y: tree.y })) focusTree(tree) }}
          onReveal={leaf => { const point = { x: tree.x + leaf.x, y: tree.y + leaf.y - 25 }; if (!pointVisible(point)) camera.move(fitPoints([point], viewport.width, viewport.height, 100)) }} />)}
      </g>
    </svg>
    {!courses.length && <p className="kt-empty">创建课程后，在树根开始第一本笔记。</p>}
    {!detailInteraction(camera.camera.k) && courses.length > 0 && <div className="kt-overview-controls" role="group" aria-label="课程概览，选择课程放大查看">
      {visible.map(tree => <button key={tree.course.course_id} onClick={() => { onFocusCourse?.(tree.course.course_id); focusTree(tree) }} aria-label={`聚焦课程：${tree.course.name}`}>{tree.course.name}<span>放大查看</span></button>)}
    </div>}
    <p className="kt-hint">根部创建或扩充 · 枝干继续阅读 · 叶片打开知识点</p>
    {selection && <TreeContents selection={{ ...selection, books: allBooks(selection.courseId) }} onClose={closeContents} onNotebook={(courseId, notebookId) => { rememberView(); onNotebook(courseId, notebookId) }} onNote={(courseId, notebookId, section) => { rememberView(); onNote(courseId, notebookId, section) }} onReveal={(_courseId, noteId) => setRevealed(noteId)} />}
  </div>
}
