import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

import {
  PET_DRAG_THRESHOLD,
  PET_FLING_SPEED,
  PET_KEY_STEP,
  PET_SNAP_RANGE,
  PET_VIEWPORT_MARGIN,
  clampToViewport,
  defaultFloatPoint,
  nearestEdge,
  pointToRatio,
  ratioToPoint,
  type PetEdge,
  type PetMode,
  type PetPoint,
  type PetSize,
  type PetViewport,
} from './petLayout'
import { FlingTracker, speedOf, stepFling, type FlingState } from './petPhysics'
import { loadPetPlacement, savePetPlacement } from './petStorage'

/**
 * 页内桌宠的拖拽状态机：rail 拖出即 float，松手可甩抛 / 贴边半隐藏 / 拖回左栏。
 * 坐标只进 ref，逐帧只写 transform（dsh-whale-girl 踩过的流式卡顿教训）；
 * React state 仅用于拖拽中、贴边这类低频视觉态。
 */

export type PetDragApi = {
  floatRef: RefObject<HTMLDivElement | null>
  dragging: boolean
  dockEdge: PetEdge | null
  onPointerDown: (event: ReactPointerEvent) => void
  onKeyDown: (event: ReactKeyboardEvent) => void
  onDoubleClick: () => void
  /** 输入区等元素获得焦点时调用：浮层若压住它就让位到最近的空白上角 */
  yieldFromRect: (rect: DOMRect | null) => void
  /** 最近一次拖拽结束的时间戳；0 表示没有拖过（用于区分点击与拖后误触） */
  lastDragAt: RefObject<number>
}

type UsePetDragOptions = {
  mode: PetMode
  size: PetSize
  /** 窄屏关闭拖拽与浮层 */
  enabled: boolean
  reducedMotion: boolean
  /** rail 被拖出瞬间，取舞台视口位置作为浮层起点 */
  getRailOrigin: () => PetPoint | null
  /** 松手时判定「拖回左栏」的区域 */
  getRailBounds: () => DOMRect | null
  onDetach: () => void
  onReturn: () => void
}

function viewport(): PetViewport {
  return { width: window.innerWidth, height: window.innerHeight }
}

function distanceToRect(point: PetPoint, rect: DOMRect): number {
  const dx = Math.max(rect.left - point.x, 0, point.x - rect.right)
  const dy = Math.max(rect.top - point.y, 0, point.y - rect.bottom)
  return Math.hypot(dx, dy)
}

export function usePetDrag(options: UsePetDragOptions): PetDragApi {
  const { mode, size, enabled, reducedMotion } = options

  const floatRef = useRef<HTMLDivElement | null>(null)
  const posRef = useRef<PetPoint>({ x: 0, y: 0 })
  const dockRef = useRef<PetEdge | null>(null)
  const [dragging, setDragging] = useState(false)
  const [dockEdge, setDockEdge] = useState<PetEdge | null>(null)
  const draggingRef = useRef(false)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    grabX: number
    grabY: number
    moved: boolean
    fromRail: boolean
    origPos: PetPoint
  } | null>(null)
  const trackerRef = useRef(new FlingTracker())
  const flingRafRef = useRef(0)
  const glideTimerRef = useRef(0)
  const initializedRef = useRef(false)
  const lastDragAtRef = useRef(0)

  const modeRef = useRef(mode)
  modeRef.current = mode
  const sizeRef = useRef(size)
  sizeRef.current = size
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const reducedRef = useRef(reducedMotion)
  reducedRef.current = reducedMotion
  const railOriginRef = useRef(options.getRailOrigin)
  railOriginRef.current = options.getRailOrigin
  const railBoundsRef = useRef(options.getRailBounds)
  railBoundsRef.current = options.getRailBounds
  const onDetachRef = useRef(options.onDetach)
  onDetachRef.current = options.onDetach
  const onReturnRef = useRef(options.onReturn)
  onReturnRef.current = options.onReturn

  const write = useCallback(() => {
    const el = floatRef.current
    if (!el) return
    el.style.transform = `translate3d(${Math.round(posRef.current.x)}px, ${Math.round(posRef.current.y)}px, 0)`
  }, [])

  const glideWrite = useCallback(() => {
    const el = floatRef.current
    if (!el) { write(); return }
    el.classList.add('is-gliding')
    write()
    window.clearTimeout(glideTimerRef.current)
    glideTimerRef.current = window.setTimeout(() => el.classList.remove('is-gliding'), 240)
  }, [write])

  const persist = useCallback(() => {
    const { xRatio, yRatio } = pointToRatio(posRef.current, viewport())
    savePetPlacement({ version: 1, mode: 'float', xRatio, yRatio })
  }, [])

  const dockTo = useCallback((edge: PetEdge) => {
    dockRef.current = edge
    setDockEdge(edge)
  }, [])

  const undock = useCallback(() => {
    if (!dockRef.current) return
    dockRef.current = null
    setDockEdge(null)
  }, [])

  const stopFling = useCallback(() => {
    if (flingRafRef.current) {
      cancelAnimationFrame(flingRafRef.current)
      flingRafRef.current = 0
    }
  }, [])

  const finishDrop = useCallback(() => {
    const vp = viewport()
    posRef.current = clampToViewport(posRef.current, sizeRef.current, vp)
    const edge = nearestEdge(posRef.current, sizeRef.current, vp)
    if (edge) dockTo(edge)
    else undock()
    write()
    persist()
  }, [dockTo, persist, undock, write])

  const startFling = useCallback((state: FlingState) => {
    let last = performance.now()
    let current = state
    const frame = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      const result = stepFling(current, dt, sizeRef.current, viewport())
      current = result.state
      posRef.current = { x: current.x, y: current.y }
      write()
      if (result.done) {
        flingRafRef.current = 0
        finishDrop()
        return
      }
      flingRafRef.current = requestAnimationFrame(frame)
    }
    stopFling()
    flingRafRef.current = requestAnimationFrame(frame)
  }, [finishDrop, stopFling, write])

  const removeWindowListeners = useCallback(() => {
    window.removeEventListener('pointermove', handleWindowMove)
    window.removeEventListener('pointerup', handleWindowUp)
    window.removeEventListener('pointercancel', handleWindowUp)
    // eslint 不可见但必须稳定：两个 handler 定义在下方，用函数声明提升绑定
  }, [])

  function handleWindowMove(event: PointerEvent) {
    const drag = dragRef.current
    if (!drag || event.pointerId !== drag.pointerId) return
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    if (!drag.moved && Math.hypot(dx, dy) < PET_DRAG_THRESHOLD) return
    if (!drag.moved) {
      drag.moved = true
      if (drag.fromRail) {
        const origin = railOriginRef.current()
        const grab = origin ?? { x: event.clientX - sizeRef.current.width / 2, y: event.clientY - sizeRef.current.height / 2 }
        drag.grabX = drag.startX - grab.x
        drag.grabY = drag.startY - grab.y
        posRef.current = origin ? { ...origin } : { ...grab }
        initializedRef.current = true
        onDetachRef.current()
      }
      undock()
      if (!draggingRef.current) {
        draggingRef.current = true
        setDragging(true)
      }
    }
    posRef.current = clampToViewport(
      { x: drag.startX + dx - drag.grabX, y: drag.startY + dy - drag.grabY },
      sizeRef.current,
      viewport(),
    )
    trackerRef.current.push(event.clientX, event.clientY)
    write()
  }

  function handleWindowUp(event: PointerEvent) {
    const drag = dragRef.current
    if (!drag || event.pointerId !== drag.pointerId) return
    dragRef.current = null
    removeWindowListeners()
    draggingRef.current = false
    setDragging(false)
    if (!drag.moved) return
    /* 只有真的拖动过才抑制随后的 click，普通点击的气泡台词不受影响 */
    lastDragAtRef.current = Date.now()
    const bounds = railBoundsRef.current()
    if (bounds
      && event.clientX >= bounds.left - PET_SNAP_RANGE
      && event.clientX <= bounds.right + 12
      && event.clientY >= bounds.top - 12
      && event.clientY <= bounds.bottom + 12) {
      onReturnRef.current()
      return
    }
    const velocity = reducedRef.current ? null : trackerRef.current.velocity()
    if (velocity && speedOf(velocity) > PET_FLING_SPEED) {
      startFling({ ...posRef.current, ...velocity })
      return
    }
    finishDrop()
  }

  const onPointerDown = useCallback((event: ReactPointerEvent) => {
    if (event.button !== 0 || !enabledRef.current) return
    stopFling()
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      grabX: event.clientX - posRef.current.x,
      grabY: event.clientY - posRef.current.y,
      moved: false,
      fromRail: modeRef.current === 'rail',
      origPos: { ...posRef.current },
    }
    trackerRef.current.reset()
    try { event.currentTarget.setPointerCapture(event.pointerId) } catch { /* 捕获失败不阻塞拖拽 */ }
    window.addEventListener('pointermove', handleWindowMove)
    window.addEventListener('pointerup', handleWindowUp)
    window.addEventListener('pointercancel', handleWindowUp)
  }, [stopFling])

  const onKeyDown = useCallback((event: ReactKeyboardEvent) => {
    if (modeRef.current !== 'float') return
    if (event.key === 'Escape') {
      const drag = dragRef.current
      stopFling()
      if (drag) {
        dragRef.current = null
        removeWindowListeners()
        draggingRef.current = false
        setDragging(false)
        lastDragAtRef.current = Date.now()
        if (!drag.fromRail) posRef.current = { ...drag.origPos }
        finishDrop()
      }
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      onReturnRef.current()
      return
    }
    const deltas: Record<string, [number, number]> = {
      ArrowLeft: [-PET_KEY_STEP, 0],
      ArrowRight: [PET_KEY_STEP, 0],
      ArrowUp: [0, -PET_KEY_STEP],
      ArrowDown: [0, PET_KEY_STEP],
    }
    const delta = deltas[event.key]
    if (!delta) return
    event.preventDefault()
    stopFling()
    undock()
    posRef.current = clampToViewport(
      { x: posRef.current.x + delta[0], y: posRef.current.y + delta[1] },
      sizeRef.current,
      viewport(),
    )
    write()
    persist()
  }, [finishDrop, persist, removeWindowListeners, stopFling, undock, write])

  const onDoubleClick = useCallback(() => {
    if (modeRef.current === 'float') onReturnRef.current()
  }, [])

  const yieldFromRect = useCallback((rect: DOMRect | null) => {
    if (!rect || modeRef.current !== 'float' || dragRef.current) return
    const vp = viewport()
    const pos = posRef.current
    const sizeNow = sizeRef.current
    const pet = { left: pos.x, top: pos.y, right: pos.x + sizeNow.width, bottom: pos.y + sizeNow.height }
    const overlaps = pet.left < rect.right && pet.right > rect.left && pet.top < rect.bottom && pet.bottom > rect.top
    if (!overlaps) return
    const candidates: PetPoint[] = [
      { x: PET_VIEWPORT_MARGIN, y: PET_VIEWPORT_MARGIN },
      { x: Math.max(PET_VIEWPORT_MARGIN, vp.width - sizeNow.width - PET_VIEWPORT_MARGIN), y: PET_VIEWPORT_MARGIN },
    ]
    const best = candidates.reduce((a, b) => (distanceToRect(b, rect) > distanceToRect(a, rect) ? b : a))
    stopFling()
    undock()
    posRef.current = clampToViewport(best, sizeNow, vp)
    glideWrite()
    persist()
  }, [glideWrite, persist, stopFling, undock])

  /* 进入浮层态：优先用存储位置（并恢复贴边），否则默认右下角 */
  useLayoutEffect(() => {
    if (mode !== 'float') return
    if (!initializedRef.current) {
      initializedRef.current = true
      const vp = viewport()
      const placement = loadPetPlacement()
      posRef.current = placement?.mode === 'float'
        ? ratioToPoint(placement, sizeRef.current, vp)
        : defaultFloatPoint(sizeRef.current, vp)
      const edge = nearestEdge(posRef.current, sizeRef.current, vp)
      if (edge) dockRef.current = edge
      setDockEdge(edge)
    }
    write()
  }, [mode, write])

  /* 视口变化：收进边界并重估贴边 */
  useEffect(() => {
    if (mode !== 'float') return
    const onResize = () => {
      stopFling()
      posRef.current = clampToViewport(posRef.current, sizeRef.current, viewport())
      const edge = nearestEdge(posRef.current, sizeRef.current, viewport())
      if (edge) dockTo(edge)
      else undock()
      write()
      persist()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [dockTo, mode, persist, stopFling, undock, write])

  useEffect(() => () => {
    removeWindowListeners()
    stopFling()
    window.clearTimeout(glideTimerRef.current)
  }, [removeWindowListeners, stopFling])

  return { floatRef, dragging, dockEdge, onPointerDown, onKeyDown, onDoubleClick, yieldFromRect, lastDragAt: lastDragAtRef }
}
