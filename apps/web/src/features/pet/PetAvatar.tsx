import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import { TeacherCharacter, type TeacherCharacterId, type TeacherStatus } from '../../components/TeacherCharacter'
import { PET_FLOAT_SIZE, type PetMode } from './petLayout'
import { usePetDrag } from './usePetDrag'

/**
 * 页内桌宠：rail 态是左栏舞台，拖出（位移 > 6px）后切到 float 态，
 * 浮层挂到 body 顶层（portal），避免被侧栏 / 抽屉的层叠上下文盖住。
 * 双击浮层或点锚点行「召回」回栏；窄屏（<900px）强制 rail，不渲染浮层。
 */

const FLOAT_HOST_ID = 'notebuddy-pet-float-host'
const FLOAT_MIN_VIEWPORT = 900

export type PetAvatarHandle = {
  yieldFromRect: (rect: DOMRect | null) => void
}

function ensureFloatHost(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  let host = document.getElementById(FLOAT_HOST_ID)
  if (!host) {
    host = document.createElement('div')
    host.id = FLOAT_HOST_ID
    document.body.appendChild(host)
  }
  return host
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof matchMedia === 'undefined') return true
    return matchMedia(query).matches
  })
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return
    const list = matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches)
    list.addEventListener('change', onChange)
    setMatches(list.matches)
    return () => list.removeEventListener('change', onChange)
  }, [query])
  return matches
}

export const PetAvatar = forwardRef<PetAvatarHandle, {
  mode: PetMode
  onModeChange: (mode: PetMode) => void
  status: TeacherStatus
  character: TeacherCharacterId
  /** 点击桌宠时冒出的上下文提示 */
  bubbleHint: string
  /** 输入区容器：浮层压住它时自动让位 */
  avoidRef?: RefObject<HTMLElement | null>
}>(function PetAvatar({ mode, onModeChange, status, character, bubbleHint, avoidRef }, ref) {
  const wide = useMediaQuery(`(min-width: ${FLOAT_MIN_VIEWPORT}px)`)
  const effectiveMode: PetMode = wide ? mode : 'rail'

  const stageRef = useRef<HTMLDivElement | null>(null)
  const railRectRef = useRef<DOMRect | null>(null)
  const bubbleTimerRef = useRef(0)
  const [bubble, setBubble] = useState<string | null>(null)

  const drag = usePetDrag({
    mode: effectiveMode,
    size: { width: PET_FLOAT_SIZE, height: PET_FLOAT_SIZE },
    enabled: wide,
    getRailOrigin: () => {
      const rect = stageRef.current?.getBoundingClientRect()
      return rect ? { x: rect.left, y: rect.top } : null
    },
    getRailBounds: () => railRectRef.current,
    onDetach: () => onModeChange('float'),
    onReturn: () => onModeChange('rail'),
  })

  useImperativeHandle(ref, () => ({
    yieldFromRect: (rect: DOMRect | null) => {
      drag.yieldFromRect(rect)
    },
  }))

  const showBubble = useCallback(() => {
    if (Date.now() - drag.lastDragAt.current < 200) return
    setBubble(bubbleHint)
    window.clearTimeout(bubbleTimerRef.current)
    bubbleTimerRef.current = window.setTimeout(() => setBubble(null), 4000)
  }, [bubbleHint, drag.lastDragAt])

  useEffect(() => () => window.clearTimeout(bubbleTimerRef.current), [])

  const handleStagePointerDown = useCallback((event: ReactPointerEvent) => {
    const rail = event.currentTarget.closest('.workspace-rail')
    railRectRef.current = rail?.getBoundingClientRect() ?? null
    drag.onPointerDown(event)
  }, [drag])

  const floatHost = useMemo(() => (effectiveMode === 'float' ? ensureFloatHost() : null), [effectiveMode])

  const bubbleNode = bubble && <span className="workspace-pet-bubble" role="status">{bubble}</span>

  return (
    <>
      {effectiveMode === 'rail' && (
        <div className="workspace-petstage">
          <span className="workspace-petstage-ripple" aria-hidden="true" />
          <div
            ref={stageRef}
            className={`workspace-petstage-drag${drag.dragging ? ' is-dragging' : ''}`}
            title="拖动我，可以浮到页面上"
            onPointerDown={handleStagePointerDown}
            onClick={showBubble}
          >
            <TeacherCharacter status={status} animated character={character} pet />
          </div>
          {bubbleNode}
        </div>
      )}
      {effectiveMode === 'float' && floatHost && createPortal(
        <div
          ref={drag.floatRef}
          className={`workspace-petfloat${drag.dockEdge ? ` is-docked-${drag.dockEdge}` : ''}${drag.dragging ? ' is-dragging' : ''}`}
          role="button"
          tabIndex={0}
          aria-label="沃雅妮莎桌宠浮层：方向键移动，Home 回左栏，双击回位"
          onPointerDown={drag.onPointerDown}
          onKeyDown={drag.onKeyDown}
          onDoubleClick={drag.onDoubleClick}
          onClick={showBubble}
        >
          <div className="workspace-petfloat-inner">
            <TeacherCharacter status={status} animated character={character} pet />
          </div>
          {bubbleNode}
        </div>,
        floatHost,
      )}
    </>
  )
})
