import { useEffect, useRef } from 'react'
import type { SlashCommand } from './slashCommands'

export function SlashCommandMenu({ items, activeIndex, position, onSelect, onHover }: {
  items: SlashCommand[]
  activeIndex: number
  position: { left: number; top: number } | null
  onSelect: (command: SlashCommand) => void
  onHover: (index: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const active = ref.current?.querySelector<HTMLElement>('[data-active="true"]')
    active?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (!position) return null
  return <div
    className="nb-slash-menu"
    ref={ref}
    style={{ left: position.left, top: position.top }}
    role="listbox"
    aria-label="插入内容块"
    onMouseDown={(event) => event.preventDefault()}
  >
    <div className="nb-slash-menu-head"><span>插入内容块</span><kbd>↑↓</kbd><kbd>↵</kbd><kbd>esc</kbd></div>
    {items.length === 0 && <p className="nb-slash-empty">没有匹配的内容块</p>}
    {items.map((command, index) => <button
      key={command.id}
      type="button"
      role="option"
      aria-selected={index === activeIndex}
      data-active={index === activeIndex}
      className={`nb-slash-item${index === activeIndex ? ' is-active' : ''}`}
      onMouseEnter={() => onHover(index)}
      onClick={() => onSelect(command)}
    >
      <span className="nb-slash-icon" aria-hidden="true">{command.icon}</span>
      <span className="nb-slash-copy"><strong>{command.label}</strong><small>{command.hint}</small></span>
      <span className="nb-slash-group">{command.group}</span>
    </button>)}
  </div>
}
