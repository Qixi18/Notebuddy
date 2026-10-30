import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { PET_SIZE_PRESETS } from './petLayout'

/**
 * 桌宠右键菜单：三档预设直接调大小。
 * 挂到 body 顶层（portal），避免被左栏 / 浮层的层叠上下文裁切；
 * 位置按右键落点，超出视口时自动收进来。
 */

const MENU_MARGIN = 8

export function PetSizeMenu({ x, y, height, onPick, onClose }: {
  x: number
  y: number
  /** 当前桌宠高度，用于高亮当前档 */
  height: number
  onPick: (height: number) => void
  onClose: () => void
}) {
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState({ left: x, top: y })

  useLayoutEffect(() => {
    const el = menuRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setPos({
      left: Math.max(MENU_MARGIN, Math.min(x, window.innerWidth - rect.width - MENU_MARGIN)),
      top: Math.max(MENU_MARGIN, Math.min(y, window.innerHeight - rect.height - MENU_MARGIN)),
    })
  }, [x, y])

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) onClose()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    const onScroll = () => onClose()
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown, true)
    window.addEventListener('resize', onScroll)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown, true)
      window.removeEventListener('resize', onScroll)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [onClose])

  return createPortal(
    <div
      ref={menuRef}
      className="pet-size-menu"
      role="menu"
      aria-label="桌宠大小"
      style={{ left: pos.left, top: pos.top }}
      onContextMenu={(event) => event.preventDefault()}
    >
      <p className="pet-size-menu-title">桌宠大小</p>
      <div className="pet-size-menu-options">
        {PET_SIZE_PRESETS.map((preset) => {
          const active = height === preset.height
          return (
            <button
              key={preset.key}
              type="button"
              role="menuitemradio"
              aria-checked={active}
              className={`pet-size-menu-option${active ? ' is-active' : ''}`}
              onClick={() => { onPick(preset.height); onClose() }}
            >
              <span className="pet-size-menu-label">{preset.label}</span>
              <span className="pet-size-menu-value">{preset.height}</span>
            </button>
          )
        })}
      </div>
      <p className="pet-size-menu-hint">右键随时调整</p>
    </div>,
    document.body,
  )
}
