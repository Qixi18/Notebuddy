import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { forestLayout, signature, TREE_SPACING, type SavedSlot, type TreePosition } from './layout'
import { arrangeForestGroves, forestTreeFrame, FOREST_SPACING, FOREST_CAPTION_BOTTOM, FOREST_LAYOUT_VERSION } from './forestGroveLayout'
import { useForestCamera } from './useForestCamera'
import { BOTANICAL_SPACING, fitPoints, notebookGeometry, overviewLeaves, overviewBranches, sceneInitialCamera, type Point } from './treeGeometry'
import { WatercolorTree } from './WatercolorTree'
import { ForestBotanicalTree } from './ForestBotanicalTree'
import { forestCanopyGeometry } from './courseCanopyGeometry'
import { groupForestVines } from './vineGroups'
import { TreeVines } from './TreeVines'
import { TreeContents, type TreeContentsSelection } from './TreeContents'
import type { KnowledgeTreeSceneProps } from './sceneTypes'
import { detailInteraction } from './treeInteraction'
import { placeLeafLabels } from './leafLabels'
import { projectNotebookControls } from './notebookControls'
import { useGrowthPlayback } from './growth/useGrowthPlayback'
import { playTreeGrowth } from './growth/paint'
import { growthVisible } from './growth/visibility'
import './knowledge-tree.css'

export type { KnowledgeTreeSceneProps, KnowledgeTreeView } from './sceneTypes'

function frameScene(points: Point[], viewport: { width: number; height: number }, mode: string, padding: number) {
  const top = mode === 'forest' ? 88 : 0
  const frame = fitPoints(points, viewport.width, Math.max(240, viewport.height - top - (top ? 16 : 0)), padding)
  return { ...frame, y: frame.y + top }
}

export function KnowledgeTreeScene({ courses, trees, mode = 'forest', initialView, onViewChange, focusCourseId, onFocusCourse, search = '', pinnedNoteIds = [], relations = [], selectedRelationId, onVisibleCourseIdsChange, onRoot, onNotebook, onNote, onRelation, className = '', toolbar, backdrop, onToggleHome, homeBusyCourseId }: KnowledgeTreeSceneProps) {
  const spacing = mode === 'forest' ? FOREST_SPACING : BOTANICAL_SPACING
  const framingMode = toolbar ? 'toolbar' : mode
  const compatibleView = mode !== 'forest' || initialView?.layoutVersion === FOREST_LAYOUT_VERSION ? initialView : undefined
  const host = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ width: initialView?.viewport.width ?? 1100, height: initialView?.viewport.height ?? 760, ready: false })
  const slots = useRef<Record<string, SavedSlot>>(initialView?.slots ?? {})
  const restored = useRef(compatibleView)
  const initialized = useRef(false)
  const contentFramed = useRef(Boolean(compatibleView))
  const firstCamera = useRef<{ x: number; y: number; k: number } | undefined>(undefined)
  const [selection, setSelection] = useState<TreeContentsSelection>()
  const [revealed, setRevealed] = useState(initialView?.revealedNoteId)
  const [relationFocus, setRelationFocus] = useState<{ id: string; point: Point }>()
  const rememberRelationPoint = useCallback((id: string, point: Point) => setRelationFocus(previous => previous?.id === id && previous.point.x === point.x && previous.point.y === point.y ? previous : { id, point }), [])
  const restoredContents = useRef(initialView?.contents)
  const contentsRestored = useRef(!initialView?.contents)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const initial = useRef(compatibleView?.camera ?? sceneInitialCamera(courses.length, viewport.width, viewport.height))
  const camera = useForestCamera(initial.current, viewport.width, viewport.height, viewport.ready, true)
  const positions = useMemo<TreePosition[]>(() => {
    // Home preserves the caller's recency order. Forest preserves semester/manual
    // order and persisted world slots. Both use exactly the same tree geometry.
    const raw = mode === 'home'
      ? courses.map((course, index) => ({ course, x: 280 + index * TREE_SPACING, y: 790, seed: index }))
      : forestLayout(courses, slots.current)
    for (const tree of raw) slots.current[tree.course.course_id] = { x: tree.x, signature: signature(tree.course) }
    return mode === 'forest' ? arrangeForestGroves(raw, spacing) : raw.map(tree => ({ ...tree, x: (tree.x - 280) / TREE_SPACING * spacing + spacing / 2 }))
  }, [courses, mode, spacing])
  const treeMap = useMemo(() => new Map(trees.map(tree => [tree.course_id, tree])), [trees])
  const branchMap = useMemo(() => new Map(trees.map(tree => [tree.course_id, tree.notebooks.filter(book => book.course_id === tree.course_id).sort((a, b) => a.tree_slot - b.tree_slot).map(notebookGeometry)])), [trees])
  const noteBooks = useMemo(() => new Map([...branchMap.values()].flatMap(branches => branches.flatMap(branch => branch.leaves.map(leaf => [leaf.section.id, branch.book.id] as const)))), [branchMap])
  const relationGroups = useMemo(() => {
    const known = new Map([...branchMap.values()].flatMap(branches => branches.flatMap(branch => branch.leaves.map(leaf => [leaf.section.id, { x: leaf.x, y: leaf.y }] as const))))
    return groupForestVines(relations, known, noteBooks)
  }, [branchMap, relations, noteBooks])
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
    if (mode === 'forest') for (const group of relationGroups) { result.add(group.relations[0].source_block_id); result.add(group.relations[0].target_block_id) }
    if (revealed) result.add(revealed)
    const selected = relations.find(relation => relation.id === selectedRelationId && relation.status === 'confirmed' && !relation.stale)
    if (selected) { result.add(selected.source_block_id); result.add(selected.target_block_id) }
    return result
  }, [pinnedNoteIds, revealed, relations, selectedRelationId, relationGroups, mode])
  const canopies = useMemo(() => new Map(positions.map(tree => [tree.course.course_id, forestCanopyGeometry(tree.course.course_id, branchMap.get(tree.course.course_id) ?? [], pins, search, selection?.notebookId)])), [positions, branchMap, pins, search, selection?.notebookId])
  const vineCourses = useMemo(() => new Map(positions.map(tree => [tree.course.course_id, { x: tree.x, y: tree.y, grove: tree.grove, canopy: canopies.get(tree.course.course_id)! }])), [positions, canopies])
  const captionExclusions = useMemo(() => mode === 'forest' ? positions.map(tree => ({ rect: { x: tree.x - 290, y: (tree.captionY ?? tree.y + 76) - 36, width: 580, height: FOREST_CAPTION_BOTTOM + 36 } })) : [], [positions, mode])
  const endpoints = useMemo(() => {
    const result = new Map<string, Point>()
    if (mode === 'forest') {
      for (const tree of positions) for (const item of canopies.get(tree.course.course_id)?.items ?? []) for (const leaf of item.leaves) {
        const radians = leaf.angle * Math.PI / 180
        result.set(leaf.section.id, { x: tree.x + leaf.x + Math.sin(radians) * 30, y: tree.y + leaf.y - Math.cos(radians) * 30 })
      }
      return result
    }
    for (const tree of positions) for (const branch of overviewBranches(branchMap.get(tree.course.course_id) ?? [], pins, search)) for (const leaf of overviewLeaves(branch, pins, search, selection?.notebookId === branch.book.id)) result.set(leaf.section.id, { x: tree.x + leaf.x, y: tree.y + leaf.y - 25 })
    return result
  }, [positions, branchMap, pins, search, selection?.notebookId, mode, canopies])
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
  const growth = useGrowthPlayback(trees, visibleKey ? visibleKey.split('|') : [], courses.map(course => course.course_id))
  const growingBooks = growth.books
  const growingNotes = growth.sections
  useEffect(() => {
    if (!growth.courses.size && !growth.books.size && !growth.sections.size) return
    const root = camera.sceneRef.current
    if (!root || !root.animate || document.visibilityState === 'hidden' || !growthVisible(root)
      || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)
      || document.querySelector('[role="dialog"], .modal-backdrop')) return
    root.classList.add('kt-growth-managed')
    const playbacks: Array<ReturnType<typeof playTreeGrowth>> = []
    if (growth.books.size || growth.sections.size) {
      playbacks.push(playTreeGrowth(root, { course: false, books: growth.books, notes: growth.sections }))
    }
    for (const tree of root.querySelectorAll<SVGGElement>('[data-course-id]')) {
      if (tree.dataset.courseId && growth.courses.has(tree.dataset.courseId) && growthVisible(tree)) {
        playbacks.push(playTreeGrowth(tree, { course: true, books: new Set(), notes: new Set() }))
      }
    }
    const finish = () => { for (const playback of playbacks) playback.finish() }
    const visibility = () => { if (document.visibilityState === 'hidden') finish() }
    root.addEventListener('pointerdown', finish, true)
    root.addEventListener('focusin', finish, true)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      root.removeEventListener('pointerdown', finish, true)
      root.removeEventListener('focusin', finish, true)
      document.removeEventListener('visibilitychange', visibility)
      finish()
      root.classList.remove('kt-growth-managed')
    }
  }, [growth, camera.sceneRef])
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
    const initialFrame = sceneInitialCamera(courses.length, viewport.width, viewport.height)
    const initialCourses = positions.slice(0, mode === 'forest' ? 3 : initialFrame.visibleCount)
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
      const points = initialCourses.flatMap(tree => {
        if (mode === 'forest') {
          const bounds = canopies.get(tree.course.course_id)!.bounds
          return forestTreeFrame(tree, bounds)
        }
        const branches = (branchMap.get(tree.course.course_id) ?? []).slice(0, 6)
        const items = branches.map(branch => ({ branch, leaves: overviewLeaves(branch, new Set(), '') }))
        const controls = projectNotebookControls(items, initialFrame.k)
        const labels = placeLeafLabels(items, initialFrame.k, controls)
        const rectangles = [...labels.map(label => label.rect), ...[...controls.values()].flatMap(control => [control.title, control.directory])]
        // Home frames the real canopy, which may have only one or two books.
        // Reserve the full course card below the roots before lazy data arrives.
        const crown = mode === 'home' ? Math.min(-490, ...branches.map(branch => branch.anchor.y - 175), ...items.flatMap(item => item.leaves.map(leaf => leaf.y - 95))) : -735
        const bottom = mode === 'home' ? ((branchMap.get(tree.course.course_id)?.length ?? 0) > 6 ? 184 : 85) : 65
        return [{ x: tree.x - 310, y: tree.y + crown }, { x: tree.x + 310, y: tree.y + bottom }, ...rectangles.flatMap(rect => [{ x: tree.x + rect.x, y: tree.y + rect.y }, { x: tree.x + rect.x + rect.width, y: tree.y + rect.y + rect.height }])]
      })
      const frame = points.length ? frameScene(points, viewport, framingMode, 30) : initialFrame
      camera.move(frame)
      firstCamera.current = frame
      if (directoriesReady) contentFramed.current = true
    }
  }, [viewport, camera.move, courses.length, positions, branchMap, treeMap, mode, canopies, framingMode])
  const callback = useRef(onViewChange)
  callback.current = onViewChange
  const rememberView = () => {
    if (viewport.ready) callback.current?.({ layoutVersion: mode === 'forest' ? FOREST_LAYOUT_VERSION : undefined, camera: { ...camera.cameraRef.current }, viewport: { width: viewport.width, height: viewport.height }, slots: { ...slots.current }, focusedCourseId: focusCourseId,
      contents: selection ? { courseId: selection.courseId, notebookId: selection.notebookId } : !contentsRestored.current ? restoredContents.current : undefined,
      revealedNoteId: revealed,
    })
  }
  useEffect(() => {
    rememberView()
  }, [camera.camera, viewport, focusCourseId, selection, revealed, trees])
  const focusTree = useCallback((tree: TreePosition) => {
    if (mode === 'forest') {
      const bounds = canopies.get(tree.course.course_id)!.bounds
      const frame = frameScene(forestTreeFrame(tree, bounds), viewport, framingMode, 48)
      // On a short canvas, keep the aligned course actions visible and let the
      // reader pan the upper crown in the operable 50% detail view.
      camera.move(frame.k >= .5 ? frame : { k: .5, x: viewport.width / 2 - tree.x * .5, y: viewport.height - 24 - ((tree.captionY ?? tree.y + 76) + FOREST_CAPTION_BOTTOM) * .5 })
      return
    }
    const branches = branchMap.get(tree.course.course_id) ?? []
    const items = branches.slice(0, 6).map(branch => ({ branch, leaves: overviewLeaves(branch, new Set(), '') }))
    const zoom = Math.max(.5, camera.cameraRef.current.k)
    const controls = projectNotebookControls(items, zoom)
    const labels = placeLeafLabels(items, zoom, controls)
    const rectangles = [...labels.map(label => label.rect), ...[...controls.values()].flatMap(control => [control.title, control.directory])]
    const bottom = mode === 'home' ? (branches.length > 6 ? 184 : 85) : 65
    const points = [{ x: tree.x - 310, y: tree.y - 735 }, { x: tree.x + 310, y: tree.y + bottom }, ...branches.slice(0, 6).flatMap(branch => branch.leaves.slice(0, 6).map(leaf => ({ x: tree.x + leaf.x, y: tree.y + leaf.y - 65 }))), ...rectangles.flatMap(rect => [{ x: tree.x + rect.x, y: tree.y + rect.y }, { x: tree.x + rect.x + rect.width, y: tree.y + rect.y + rect.height }])]
    const framed = fitPoints(points, viewport.width, viewport.height, 30)
    // Course overview controls promise to enter an operable detail view. On a
    // short canvas preserve the root and let the user pan the upper canopy.
    camera.move(framed.k >= .5 ? framed : { k: .75, x: viewport.width / 2 - tree.x * .75, y: viewport.height * .82 - tree.y * .75 })
  }, [branchMap, camera.move, viewport.width, viewport.height, mode, canopies, framingMode])
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
    if (selected) { ids.add(selected.source_block_id); ids.add(selected.target_block_id) }
    return ids
  }, [revealed, relations, selectedRelationId])
  // Different relations may share both notes but occupy different vine leaves.
  const pinKey = focusPins.size ? `${[...focusPins].sort().join('|')}::${selectedRelationId ?? ''}` : ''
  const lastPinFocus = useRef(compatibleView ? pinKey : '')
  useEffect(() => {
    if (!viewport.ready || !pinKey || pinKey === lastPinFocus.current) return
    const points = [...focusPins].flatMap(id => endpoints.has(id) ? [endpoints.get(id)!] : [])
    // A selected relation can load its two directories separately. Do not mark
    // this pin set framed until every requested real endpoint is available.
    if (points.length !== focusPins.size) return
    const selected = relations.find(relation => relation.id === selectedRelationId && relation.status === 'confirmed' && !relation.stale)
    if (mode === 'forest' && selected) {
      if (relationFocus?.id !== selected.id) return
      points.push(relationFocus.point)
    }
    camera.move(frameScene(points, viewport, framingMode, 100))
    lastPinFocus.current = pinKey
  }, [pinKey, focusPins, endpoints, viewport, camera.move, selectedRelationId, relations, relationFocus, mode, framingMode])
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
  const fit = () => camera.move(frameScene(positions.flatMap(tree => {
    if (mode === 'forest') {
      const bounds = canopies.get(tree.course.course_id)!.bounds
      return forestTreeFrame(tree, bounds)
    }
    return [{ x: tree.x - 280, y: tree.y - 735 }, { x: tree.x + 280, y: tree.y + ((branchMap.get(tree.course.course_id)?.length ?? 0) > 6 ? 184 : 85) }]
  }), viewport, framingMode, 30))
  const controls = <div className="kt-camera-controls" role="group" aria-label="知识树画布控制">
      <button aria-label="向左浏览课程" onClick={() => camera.pan(spacing * camera.camera.k)}>‹</button>
      <button aria-label="缩小知识树" onClick={() => camera.scale(1 / 1.2)}>−</button>
      <output aria-label="知识树缩放">{Math.round(camera.camera.k * 100)}%</output>
      <button aria-label="放大知识树" onClick={() => camera.scale(1.2)}>+</button>
      <button aria-label="适应全部课程" onClick={fit}>适应</button>
      <button aria-label="向右浏览课程" onClick={() => camera.pan(-spacing * camera.camera.k)}>›</button>
    </div>
  const scene = <div ref={host} className={`knowledge-tree-scene ${className}`} data-scene-mode={mode}>
    {backdrop}
    {!toolbar && controls}
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
        <TreeVines relations={relations} endpoints={endpoints} noteBooks={noteBooks} courseGeometry={mode === 'forest' ? vineCourses : undefined} layout={mode === 'forest' ? 'grove' : 'row'} leafExclusions={captionExclusions} viewKey={`${camera.camera.x},${camera.camera.y},${camera.camera.k}`} zoom={camera.camera.k} selectedId={selectedRelationId} onSelectedPoint={rememberRelationPoint} onRelation={relation => { rememberView(); onRelation(relation) }} />
        {visible.map(tree => {
          const Tree = mode === 'forest' ? ForestBotanicalTree : WatercolorTree
          return <Tree key={tree.course.course_id} tree={tree} canopy={canopies.get(tree.course.course_id)!} viewKey={`${camera.camera.x},${camera.camera.y},${camera.camera.k}`} garden={mode === 'home'} branches={branchMap.get(tree.course.course_id) ?? []} zoom={camera.camera.k} pins={mode === 'forest' ? focusPins : pins} growingNotes={growingNotes} growingBooks={growingBooks} search={search} expandedBookId={selection?.notebookId} onToggleHome={onToggleHome ? () => onToggleHome(tree.course.course_id) : undefined} homeBusy={Boolean(homeBusyCourseId)}
          onRoot={() => { rememberView(); onRoot(tree.course.course_id) }} onNotebook={book => { rememberView(); onNotebook(tree.course.course_id, book.id) }} onNote={(book, section) => { rememberView(); onNote(tree.course.course_id, book.id, section) }}
          onExpand={book => openContents(tree.course.course_id, tree.course.name, book.id)} onExpandBooks={() => openContents(tree.course.course_id, tree.course.name)}
          onFocus={() => { onFocusCourse?.(tree.course.course_id); if (!detailInteraction(camera.cameraRef.current.k) || !pointVisible({ x: tree.x, y: tree.captionY ?? tree.y })) focusTree(tree) }}
          onReveal={leaf => { const point = { x: tree.x + leaf.x, y: tree.y + leaf.y - 25 }; if (!pointVisible(point)) camera.move(fitPoints([point], viewport.width, viewport.height, 100)) }} />
        })}
      </g>
    </svg>
    {!courses.length && <p className="kt-empty">创建课程后，在树根开始第一本笔记。</p>}
    {(mode === 'forest' ? camera.camera.k < .3 : !detailInteraction(camera.camera.k)) && courses.length > 0 && <div className="kt-overview-controls" role="group" aria-label="课程概览，选择课程放大查看">
      {visible.map(tree => <button key={tree.course.course_id} onClick={() => { onFocusCourse?.(tree.course.course_id); focusTree(tree) }} aria-label={`聚焦课程：${tree.course.name}`}>{tree.course.name}<span>放大查看</span></button>)}
    </div>}
    <p className="kt-hint">根部创建或扩充 · 枝干继续阅读 · 叶片打开知识点</p>
    {selection && <TreeContents selection={{ ...selection, books: allBooks(selection.courseId) }} onClose={closeContents} onNotebook={(courseId, notebookId) => { rememberView(); onNotebook(courseId, notebookId) }} onNote={(courseId, notebookId, section) => { rememberView(); onNote(courseId, notebookId, section) }} onReveal={(_courseId, noteId) => setRevealed(noteId)} />}
  </div>
  return toolbar ? <div className="kt-workspace"><div className="kt-toolbar">{toolbar}{controls}</div>{scene}</div> : scene
}
