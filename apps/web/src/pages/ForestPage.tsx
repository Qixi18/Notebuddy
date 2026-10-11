import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { curveCatmullRom, line } from 'd3-shape'
import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import { CurriculumImportPanel } from '../features/forest/CurriculumImportPanel'
import { ForestCoursePanel } from '../features/forest/ForestCoursePanel'
import { ForestRelationsPanel } from '../features/forest/ForestRelationsPanel'
import { ForestTree } from '../features/forest/ForestTree'
import {
  forestLayout,
  signature,
  treeLeaves,
  visibleCourses,
  type SavedSlot,
} from '../features/forest/layout'
import {
  FOREST_SLOTS_KEY,
  FOREST_VIEW_KEY,
  forestNotePath,
  restoreForestState,
} from '../features/forest/navigation'
import { useForestCamera } from '../features/forest/useForestCamera'
import type { CrossCourseRelation, ForestCourse, ForestJob } from '../features/forest/types'
import type { Notebook, NotebookSection } from '../types'
import '../features/forest/forest.css'

type SearchResult = {
  course_id: string
  course_name: string
  note_id: string
  title: string
  material_id: string | null
}
const curve = line<[number, number]>().curve(curveCatmullRom.alpha(0.7))
function readSlots(): Record<string, SavedSlot> {
  try {
    return JSON.parse(localStorage.getItem(FOREST_SLOTS_KEY) ?? '{}') as Record<string, SavedSlot>
  } catch {
    return {}
  }
}
function readView() {
  try {
    return restoreForestState(sessionStorage.getItem(FOREST_VIEW_KEY))
  } catch {
    return undefined
  }
}

export function ForestPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useSearchParams()
  const queryCourse = query.get('course')
  const { refreshCourses } = useWorkspace()
  const restored = useRef(readView()).current
  const slots = useRef(readSlots())
  const [courses, setCourses] = useState<ForestCourse[]>([])
  const [relations, setRelations] = useState<CrossCourseRelation[]>([])
  const [books, setBooks] = useState<Record<string, Notebook>>({})
  const [bookErrors, setBookErrors] = useState<Record<string, string>>({})
  const requested = useRef(new Set<string>())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [focusId, setFocusId] = useState(query.get('course') ?? restored?.focus)
  const [expanded, setExpanded] = useState(new Set(restored?.expanded ?? []))
  const [dialog, setDialog] = useState<'import' | 'relations'>()
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searchError, setSearchError] = useState<string>()
  const [searching, setSearching] = useState(false)
  const [job, setJob] = useState<ForestJob>()
  const surfaceRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({
    width: restored?.viewport?.width ?? 1100,
    height: restored?.viewport?.height ?? 760,
    measured: Boolean(restored?.viewport) || typeof ResizeObserver === 'undefined',
  })
  const camera = useForestCamera(
    restored?.camera ?? { x: 15, y: -125, k: 0.95 },
    size.width,
    size.height,
    size.measured,
  )
  const trees = useMemo(() => forestLayout(courses, slots.current), [courses])
  const visibleIds = visibleCourses(trees, camera.camera, size.width)
  const visibleKey = [...new Set([...visibleIds, ...(focusId ? [focusId] : [])])].sort().join('|')
  const activeTree = trees.find((tree) => tree.course.course_id === focusId)
  const activeBook = focusId ? books[focusId] : undefined
  const worldWidth = Math.max(1400, ...trees.map((tree) => tree.x + 330))
  const visibleRelations = relations.filter(
    (relation) =>
      relation.status === 'confirmed' &&
      !relation.stale &&
      visibleIds.includes(relation.source_course_id) &&
      visibleIds.includes(relation.target_course_id),
  )
  const endpoints = new Set(
    visibleRelations.flatMap((relation) => [relation.source_note_id, relation.target_note_id]),
  )
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    if (!surfaceRef.current || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height, measured: true }),
    )
    observer.observe(surfaceRef.current)
    return () => observer.disconnect()
  }, [])
  const reload = useCallback(async () => {
    const [forest, links] = await Promise.allSettled([api.getForest(), api.getForestRelations()])
    if (!mounted.current) return
    if (forest.status === 'fulfilled') setCourses(forest.value.courses)
    else setError(forest.reason instanceof Error ? forest.reason.message : '森林读取失败')
    if (links.status === 'fulfilled') setRelations(links.value)
    else setError(links.reason instanceof Error ? links.reason.message : '关联读取失败')
    setLoading(false)
  }, [])
  useEffect(() => {
    void reload()
  }, [reload])
  useEffect(() => {
    for (const tree of trees)
      slots.current[tree.course.course_id] = { x: tree.x, signature: signature(tree.course) }
    try {
      localStorage.setItem(FOREST_SLOTS_KEY, JSON.stringify(slots.current))
    } catch {
      /* The scene remains usable when storage is unavailable. */
    }
  }, [trees])
  useEffect(() => {
    for (const id of visibleKey.split('|').filter(Boolean)) {
      if (requested.current.has(id)) continue
      requested.current.add(id)
      void api
        .getNotebook(id)
        .then((book) => {
          if (mounted.current) setBooks((current) => ({ ...current, [id]: book }))
        })
        .catch((cause) => {
          if (mounted.current)
            setBookErrors((current) => ({
              ...current,
              [id]: cause instanceof Error ? cause.message : '课程目录读取失败',
            }))
        })
    }
  }, [visibleKey])
  const saveView = useCallback(() => {
    try {
      sessionStorage.setItem(
        FOREST_VIEW_KEY,
        JSON.stringify({
          camera: camera.cameraRef.current,
          ...(size.measured ? { viewport: { width: size.width, height: size.height } } : {}),
          focus: focusId,
          expanded: [...expanded],
        }),
      )
    } catch {
      /* Browser storage is optional. */
    }
  }, [camera.cameraRef, focusId, expanded, size])
  useEffect(() => {
    const timer = window.setTimeout(saveView, 180)
    return () => window.clearTimeout(timer)
  }, [camera.camera, saveView])
  useEffect(() => {
    if (queryCourse) setFocusId(queryCourse)
  }, [queryCourse])
  const focusedOnce = useRef(restored?.focus)
  const narrowViewport = useRef<boolean | undefined>(undefined)
  useEffect(() => {
    if (!size.measured) return
    const narrow = size.width <= 760
    const changedLayout = narrowViewport.current !== undefined && narrowViewport.current !== narrow
    narrowViewport.current = narrow
    if (!activeTree || (focusedOnce.current === focusId && !changedLayout)) return
    camera.focus(activeTree.x + (narrow ? 0 : 140), activeTree.y)
    if (activeBook && !expanded.size)
      setExpanded(new Set(activeBook.chapters.slice(0, 1).map((chapter) => chapter.id)))
    focusedOnce.current = focusId
  }, [activeTree, activeBook, focusId, camera.focus, expanded.size, size.width, size.measured])
  useEffect(() => {
    if (!activeBook || !focusId || expanded.size) return
    setExpanded(new Set(activeBook.chapters.slice(0, 1).map((chapter) => chapter.id)))
  }, [activeBook, focusId])
  useEffect(() => {
    const value = search.trim()
    setSearchError(undefined)
    if (!value) {
      setResults([])
      setSearching(false)
      return
    }
    let active = true
    setSearching(true)
    const timer = window.setTimeout(() => {
      void api
        .searchForest(value)
        .then((next) => {
          if (active) setResults(next)
        })
        .catch((cause) => {
          if (active) {
            setResults([])
            setSearchError(cause instanceof Error ? cause.message : '知识搜索失败')
          }
        })
        .finally(() => {
          if (active) setSearching(false)
        })
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [search])
  const jobId = job?.id,
    jobStatus = job?.status
  useEffect(() => {
    setJob(undefined)
    if (!focusId) return
    let active = true
    void api
      .getLatestForestJob(focusId)
      .then((latest) => {
        if (active && latest) setJob(latest)
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : '自动关联任务读取失败')
      })
    return () => {
      active = false
    }
  }, [focusId])
  useEffect(() => {
    if (!jobId || (jobStatus !== 'pending' && jobStatus !== 'processing')) return
    let active = true,
      inFlight = false
    const timer = window.setInterval(() => {
      if (inFlight) return
      inFlight = true
      void api
        .getForestJob(jobId)
        .then((next) => {
          if (!active) return
          setJob(next)
          if (next.status === 'completed') void reload()
        })
        .catch((cause) => {
          if (active) setError(cause instanceof Error ? cause.message : '任务读取失败')
        })
        .finally(() => {
          inFlight = false
        })
    }, 1500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [jobId, jobStatus, reload])
  function focusCourse(id: string) {
    setFocusId(id)
    setExpanded(new Set())
    focusedOnce.current = undefined
    setQuery({ course: id }, { replace: true })
    setSearch('')
  }
  function exitFocus() {
    setFocusId(undefined)
    setQuery({}, { replace: true })
    focusedOnce.current = undefined
  }
  function openNote(courseId: string, section: Pick<NotebookSection, 'id' | 'material_id'>) {
    saveView()
    navigate(forestNotePath(courseId, section), {
      state: {
        fromForest: true,
        forestReturn: focusId ? `/forest?course=${encodeURIComponent(focusId)}` : '/forest',
      },
    })
  }
  function fit() {
    if (!activeTree || !activeBook) return
    const leaves = treeLeaves(activeBook, expanded, endpoints)
    const top = activeTree.y + Math.min(-450, ...leaves.map((leaf) => leaf.y - 42))
    const contentHeight = activeTree.y + 115 - top
    const k = Math.max(0.35, Math.min(1.25, (size.height - 80) / contentHeight))
    camera.move({
      x: (size.width - (size.width > 760 ? 320 : 0)) / 2 - activeTree.x * k,
      y: 40 - top * k,
      k,
    })
  }
  function handleKeys(event: KeyboardEvent<SVGSVGElement>) {
    if (event.target !== event.currentTarget) return
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [180, 0],
      ArrowRight: [-180, 0],
      ArrowUp: [0, 140],
      ArrowDown: [0, -140],
    }
    if (moves[event.key]) {
      event.preventDefault()
      camera.pan(...moves[event.key])
    }
    if (event.key === '+' || event.key === '=') {
      event.preventDefault()
      camera.scale(1.2)
    }
    if (event.key === '-') {
      event.preventDefault()
      camera.scale(1 / 1.2)
    }
    if (event.key === 'Home') {
      event.preventDefault()
      camera.move({ x: 15, y: -125, k: 0.95 })
    }
    if (event.key === 'Escape') exitFocus()
  }
  const leafPositions = new Map<string, { x: number; y: number }>()
  for (const tree of trees.filter((item) => visibleIds.includes(item.course.course_id))) {
    const book = books[tree.course.course_id]
    if (book)
      for (const leaf of treeLeaves(
        book,
        tree.course.course_id === focusId ? expanded : undefined,
        endpoints,
      ))
        leafPositions.set(leaf.section.id, { x: tree.x + leaf.x, y: tree.y + leaf.y })
  }
  const vines = relations.filter(
    (relation) =>
      relation.status === 'confirmed' &&
      !relation.stale &&
      leafPositions.has(relation.source_note_id) &&
      leafPositions.has(relation.target_note_id),
  )
  const terrainLeft = -camera.camera.x / camera.camera.k - 600,
    terrainRight = (size.width - camera.camera.x) / camera.camera.k + 600
  const courseMatches = search.trim()
    ? courses
        .filter((course) => course.name.toLowerCase().includes(search.trim().toLowerCase()))
        .slice(0, 8)
    : []
  return (
    <div className="forest-page">
      <header className="forest-header">
        <div className="forest-heading">
          <svg viewBox="0 0 48 48" aria-hidden="true">
            <path d="M24 42V16m0 15-11-9m11 0 10-10M22 19C10 19 6 10 10 5c10 0 18 4 12 14Zm4-5C28 3 37 2 42 6c-2 8-8 13-16 8Z" />
          </svg>
          <div>
            <h1>知识森林</h1>
            <p>沿着学期，让知识慢慢生长</p>
          </div>
        </div>
        <div className="forest-header-actions">
          <button type="button" onClick={() => setDialog('relations')}>
            跨课藤蔓
            {relations.some((r) => r.status === 'pending') && (
              <span className="forest-pending-count">
                {relations.filter((r) => r.status === 'pending').length}
              </span>
            )}
          </button>
          <button type="button" className="forest-action" onClick={() => setDialog('import')}>
            导入培养方案
          </button>
        </div>
      </header>
      <div className="forest-surface" ref={surfaceRef}>
        <div className="forest-search">
          <label>
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <circle cx="8" cy="8" r="5.5" />
              <path d="m12 12 5 5" />
            </svg>
            <input
              aria-label="搜索课程或知识点"
              placeholder="寻找课程或知识点"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          {search.trim() && (
            <div className="forest-search-results" aria-label="搜索结果">
              {courseMatches.map((course) => (
                <button
                  key={course.course_id}
                  type="button"
                  onClick={() => focusCourse(course.course_id)}
                >
                  <span>课程</span>
                  <strong>{course.name}</strong>
                  <small>{course.semester ? `第${course.semester}学期` : '未安排学期'}</small>
                </button>
              ))}
              {results.map((result) => (
                <button
                  key={result.note_id}
                  type="button"
                  onClick={() =>
                    openNote(result.course_id, {
                      id: result.note_id,
                      material_id: result.material_id,
                    })
                  }
                >
                  <span>笔记</span>
                  <strong>{result.title}</strong>
                  <small>{result.course_name}</small>
                </button>
              ))}
              {searching && <p role="status">寻找知识点…</p>}
              {searchError && <p role="alert">{searchError}</p>}
              {!searching && !searchError && !results.length && !courseMatches.length && (
                <p>没有找到，试试其他课程名或关键词。</p>
              )}
            </div>
          )}
        </div>
        <div className="forest-legend" aria-label="课程学习状态">
          <span>
            <i className="forest-state-planned" />
            未开始
          </span>
          <span>
            <i className="forest-state-learning" />
            在学
          </span>
          <span>
            <i className="forest-state-completed" />
            已完成
          </span>
        </div>
        <svg
          ref={camera.svgRef}
          className="forest-canvas"
          width={size.width}
          height={size.height}
          role="group"
          aria-label="知识森林画布；方向键平移，加减键缩放，Home 回到起点"
          tabIndex={0}
          onKeyDown={handleKeys}
        >
          <defs>
            <pattern id="forest-paper" width="140" height="100" patternUnits="userSpaceOnUse">
              <circle cx="19" cy="26" r=".5" fill="#8b9674" />
              <circle cx="93" cy="62" r=".6" fill="#8b9674" />
              <path d="m38 89 2 1m72-76 1 2" stroke="#8b9674" strokeWidth=".45" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#forest-paper)" opacity=".22" />
          <g
            ref={camera.sceneRef}
            transform={`translate(${camera.camera.x},${camera.camera.y}) scale(${camera.camera.k})`}
          >
            <path
              d={`M${terrainLeft} 845 Q${terrainLeft + 350} 785 ${terrainLeft + 700} 825 T${terrainLeft + 1400} 823 T${terrainLeft + 2100} 818 T${terrainRight + 700} 826 L${terrainRight + 700} 1800 H${terrainLeft}Z`}
              fill="#e5ecdb"
              opacity=".42"
            />
            <path
              d={`M${terrainLeft} 861 Q${terrainLeft + 420} 823 ${terrainLeft + 800} 867 T${terrainLeft + 1600} 849 T${terrainRight + 600} 865`}
              fill="none"
              stroke="#b8c5a7"
              strokeWidth="1.3"
              opacity=".5"
            />
            {trees
              .filter(
                (tree, index) =>
                  (index === 0 || trees[index - 1].course.semester !== tree.course.semester) &&
                  visibleIds.includes(tree.course.course_id),
              )
              .map((tree) => (
                <g key={`semester-${tree.course.course_id}`} className="forest-semester-mark">
                  <path d={`M${tree.x - 190} 940h110`} stroke="#a2b296" strokeWidth="1" />
                  <text x={tree.x - 190} y="922">
                    {tree.course.semester ? `第 ${tree.course.semester} 学期` : '学期未安排'}
                  </text>
                </g>
              ))}
            {vines.map((relation) => {
              const a = leafPositions.get(relation.source_note_id)!,
                b = leafPositions.get(relation.target_note_id)!
              const path =
                curve([
                  [a.x, a.y],
                  [a.x + (b.x - a.x) * 0.3, Math.max(a.y, b.y) + 65],
                  [a.x + (b.x - a.x) * 0.7, Math.max(a.y, b.y) + 92],
                  [b.x, b.y],
                ]) ?? ''
              return (
                <g
                  className="forest-vine"
                  key={relation.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`跨课程关联：${relation.source_title}与${relation.target_title}`}
                  data-forest-interactive="true"
                  onClick={() => setDialog('relations')}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') setDialog('relations')
                  }}
                >
                  <title>{relation.reason}</title>
                  <path
                    d={path}
                    stroke="#71836a"
                    strokeWidth="1.7"
                    fill="none"
                    strokeDasharray={relation.relation_type === 'prerequisite' ? '6 4' : undefined}
                  />
                  <path d={path} stroke="transparent" strokeWidth="18" fill="none" />
                </g>
              )
            })}
            {trees
              .filter((tree) => visibleIds.includes(tree.course.course_id))
              .map((tree) => (
                <ForestTree
                  key={tree.course.course_id}
                  tree={tree}
                  book={books[tree.course.course_id]}
                  focused={focusId === tree.course.course_id}
                  expanded={expanded}
                  endpoints={endpoints}
                  onFocus={() => focusCourse(tree.course.course_id)}
                  onOpen={(section) => openNote(tree.course.course_id, section)}
                  search={search.trim()}
                />
              ))}
          </g>
        </svg>
        {loading && (
          <p role="status" className="forest-scene-message">
            正在打开森林…
          </p>
        )}
        {error && (
          <div className="forest-scene-error" role="alert">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => {
                setError(undefined)
                void reload()
              }}
            >
              重新读取
            </button>
          </div>
        )}
        {!loading && !courses.length && !error && (
          <div className="forest-scene-empty">
            <h2>你的森林，从一门课程开始</h2>
            <p>导入培养方案，种下接下来几个学期的课程。每一讲笔记都会长出真实的知识叶子。</p>
            <button type="button" className="forest-action" onClick={() => setDialog('import')}>
              导入培养方案
            </button>
            <button
              type="button"
              onClick={() => navigate('/', { state: { openCreateCourse: true } })}
            >
              手动创建课程
            </button>
          </div>
        )}
        {activeTree && (
          <ForestCoursePanel
            key={`${focusId}:${activeTree.course.revision}`}
            course={activeTree.course}
            book={activeBook}
            expanded={expanded}
            onExpand={(id) =>
              setExpanded((current) => (current.has(id) ? new Set() : new Set([id])))
            }
            onClose={exitFocus}
            onUpdated={(next) => {
              setCourses((current) =>
                current.map((course) => (course.course_id === next.course_id ? next : course)),
              )
              focusedOnce.current = undefined
            }}
            onOpen={(section) => openNote(activeTree.course.course_id, section)}
            onFit={fit}
            onJob={setJob}
          />
        )}
        {focusId && bookErrors[focusId] && (
          <div className="forest-outline-error" role="alert">
            {bookErrors[focusId]}
            <button
              type="button"
              onClick={() => {
                requested.current.delete(focusId)
                void api
                  .getNotebook(focusId)
                  .then((book) => {
                    setBooks((current) => ({ ...current, [focusId]: book }))
                    setBookErrors((current) => {
                      const next = { ...current }
                      delete next[focusId]
                      return next
                    })
                  })
                  .catch((cause) =>
                    setError(cause instanceof Error ? cause.message : '目录读取失败'),
                  )
              }}
            >
              重试目录
            </button>
          </div>
        )}
        <div className="forest-camera-controls" role="group" aria-label="森林视口控制">
          <button
            type="button"
            aria-label="向左移动森林视口"
            onClick={() => camera.pan(size.width * 0.65)}
          >
            ←
          </button>
          <button
            type="button"
            aria-label="向右移动森林视口"
            onClick={() => camera.pan(-size.width * 0.65)}
          >
            →
          </button>
          <span />
          <button type="button" aria-label="缩小森林" onClick={() => camera.scale(1 / 1.2)}>
            −
          </button>
          <output aria-label="缩放比例">{Math.round(camera.camera.k * 100)}%</output>
          <button type="button" aria-label="放大森林" onClick={() => camera.scale(1.2)}>
            ＋
          </button>
          <button
            type="button"
            className="forest-reset-camera"
            onClick={() => camera.move({ x: 15, y: -125, k: 0.95 })}
          >
            回到起点
          </button>
        </div>
        {courses.length > 0 && (
          <div className="forest-minimap">
            <span>森林地图 · {courses.length} 门课程</span>
            <svg width="200" height="54" viewBox="0 0 200 54" role="group" aria-label="森林小地图">
              <path d="M3 44 Q50 36 100 43T197 41" stroke="#c5cfb6" fill="none" />
              {trees.map((tree) => (
                <circle
                  key={tree.course.course_id}
                  cx={(tree.x / worldWidth) * 194 + 3}
                  cy={(tree.y / 1000) * 45}
                  r={tree.course.course_id === focusId ? 3.7 : 2.3}
                  fill={
                    tree.course.learning_state === 'planned'
                      ? '#a7b39c'
                      : tree.course.learning_state === 'completed'
                        ? '#376649'
                        : '#719465'
                  }
                  role="button"
                  tabIndex={0}
                  aria-label={`地图定位${tree.course.name}`}
                  onClick={() => {
                    camera.focus(tree.x, tree.y)
                    focusCourse(tree.course.course_id)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') focusCourse(tree.course.course_id)
                  }}
                />
              ))}
              <rect
                x={Math.max(0, (-camera.camera.x / camera.camera.k / worldWidth) * 194)}
                y="6"
                width={Math.min(200, (size.width / camera.camera.k / worldWidth) * 194)}
                height="42"
                rx="3"
                fill="#729265"
                opacity=".13"
                stroke="#59794f"
                strokeWidth="1"
                pointerEvents="none"
              />
            </svg>
          </div>
        )}
        <p className="forest-navigation-hint">
          拖动画布漫步 · 滚轮缩放 · 点击树名展开讲次 · 叶子进入笔记
        </p>
        {job && (
          <div className={`forest-job-toast forest-job-${job.status}`} role="status">
            <span>
              {job.status === 'failed'
                ? (job.error_message ?? '关联任务失败')
                : job.status === 'completed'
                  ? '关联建议已生成，打开跨课藤蔓核对'
                  : `正在寻找跨课程关联 · ${job.progress}%`}
            </span>
            {job.status === 'failed' && (
              <button
                type="button"
                onClick={() =>
                  void api
                    .retryForestJob(job.id)
                    .then(setJob)
                    .catch((cause) => setError(cause instanceof Error ? cause.message : '重试失败'))
                }
              >
                重试
              </button>
            )}
            {job.status === 'completed' && (
              <button type="button" onClick={() => setDialog('relations')}>
                查看建议
              </button>
            )}
            <button type="button" aria-label="关闭任务提示" onClick={() => setJob(undefined)}>
              ×
            </button>
          </div>
        )}
      </div>
      {dialog === 'relations' && (
        <ForestRelationsPanel
          relations={relations}
          courses={courses}
          onChange={() => void reload()}
          onClose={() => setDialog(undefined)}
        />
      )}
      {dialog === 'import' && (
        <CurriculumImportPanel
          courses={courses}
          onConfirmed={() => {
            void reload()
            void refreshCourses()
          }}
          onClose={() => setDialog(undefined)}
        />
      )}
    </div>
  )
}
