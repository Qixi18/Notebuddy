import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import { TeacherCharacter, type TeacherStatus } from '../../components/TeacherCharacter'
import { PetSizeMenu } from './PetSizeMenu'
import { PET_SIZE_DEFAULT, petBoxSize, type PetMode } from './petLayout'
import { loadPetPlacement, savePetSize } from './petStorage'
import { usePetAction } from './usePetAction'
import { usePetDrag } from './usePetDrag'
import { usePetEasterEggs } from './usePetEasterEggs'

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
  /** 正文是否正在流式输出：一旦开始吐字就切讲解 */
  streaming?: boolean
  /** 点击桌宠时冒出的上下文提示 */
  bubbleHint: string
  /** 输入框草稿：彩蛋「停笔」据此计时 */
  draft?: string
  /** 输入区容器：浮层压住它时自动让位 */
  avoidRef?: RefObject<HTMLElement | null>
}>(function PetAvatar({ mode, onModeChange, status, streaming = false, bubbleHint, draft = '', avoidRef }, ref) {
  const wide = useMediaQuery(`(min-width: ${FLOAT_MIN_VIEWPORT}px)`)
  const effectiveMode: PetMode = wide ? mode : 'rail'

  const stageRef = useRef<HTMLDivElement | null>(null)
  const railRectRef = useRef<DOMRect | null>(null)
  const bubbleTimerRef = useRef(0)
  const [bubble, setBubble] = useState<string | null>(null)
  /* 桌宠高度（栏内与浮层共用）：默认取本地记忆，右键菜单可调 */
  const [height, setHeight] = useState(() => loadPetPlacement()?.size ?? PET_SIZE_DEFAULT)
  const box = useMemo(() => petBoxSize(height), [height])
  const [sizeMenuAt, setSizeMenuAt] = useState<{ x: number; y: number } | null>(null)
  /* 悬停 3 秒触发行礼，其余动作由 status 跃迁驱动 */
  const [hovered, setHovered] = useState(false)
  /* 彩蛋：连点 / 重问 / 夜场 / 停笔 / 离开归来，各会话只放一次 */
  const eggs = usePetEasterEggs({ busy: status === 'thinking', draft })
  const { src: petSrc } = usePetAction(status, hovered, streaming, eggs.command)

  const drag = usePetDrag({
    mode: effectiveMode,
    size: box,
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

  const showBubble = useCallback((text?: string) => {
    if (Date.now() - drag.lastDragAt.current < 200) return
    setBubble(text ?? bubbleHint)
    window.clearTimeout(bubbleTimerRef.current)
    bubbleTimerRef.current = window.setTimeout(() => setBubble(null), text ? 5000 : 4000)
  }, [bubbleHint, drag.lastDragAt])

  /* 彩蛋台词：直接用彩蛋自己的文案，盖掉默认点击提示 */
  const eggNonce = eggs.command?.nonce ?? 0
  useEffect(() => {
    if (!eggs.command || !eggNonce) return
    showBubble(eggs.command.bubble)
    // 只认 nonce：同一条命令不重复展示
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eggNonce])

  useEffect(() => () => window.clearTimeout(bubbleTimerRef.current), [])

  const handleStagePointerDown = useCallback((event: ReactPointerEvent) => {
    const rail = event.currentTarget.closest('.workspace-rail')
    railRectRef.current = rail?.getBoundingClientRect() ?? null
    drag.onPointerDown(event)
  }, [drag])

  /* 右键：在落点弹出大小菜单（左栏与浮层共用） */
  const openSizeMenu = useCallback((event: ReactMouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    setSizeMenuAt({ x: event.clientX, y: event.clientY })
  }, [])

  const closeSizeMenu = useCallback(() => setSizeMenuAt(null), [])

  const pickSize = useCallback((next: number) => {
    setHeight(next)
    savePetSize(next)
  }, [])

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
            style={{ width: box.width, height: box.height }}
            title="拖动我，可以浮到页面上；右键调整大小"
            onPointerDown={handleStagePointerDown}
            onClick={() => { eggs.noteClick(); showBubble() }}
            onContextMenu={openSizeMenu}
            onPointerEnter={() => setHovered(true)}
            onPointerLeave={() => setHovered(false)}
          >
            <TeacherCharacter status={status} pet src={petSrc} />
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
          style={{ width: box.width, height: box.height }}
          aria-label="沃雅妮莎桌宠浮层：方向键移动，Home 回左栏，双击回位，右键调整大小"
          onPointerDown={drag.onPointerDown}
          onKeyDown={drag.onKeyDown}
          onDoubleClick={drag.onDoubleClick}
          onClick={() => { eggs.noteClick(); showBubble() }}
          onContextMenu={openSizeMenu}
          onPointerEnter={() => setHovered(true)}
          onPointerLeave={() => setHovered(false)}
        >
          <div className="workspace-petfloat-inner">
            <TeacherCharacter status={status} pet src={petSrc} />
          </div>
          {bubbleNode}
        </div>,
        floatHost,
      )}
      {sizeMenuAt && (
        <PetSizeMenu x={sizeMenuAt.x} y={sizeMenuAt.y} height={height} onPick={pickSize} onClose={closeSizeMenu} />
      )}
    </>
  )
})
