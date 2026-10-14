import type { ReactNode, KeyboardEvent } from 'react'

export function TreeAction({ label, onActivate, children, className = '', transform, onFocus }: {
  label: string; onActivate: () => void; children: ReactNode
  className?: string; transform?: string; onFocus?: () => void
}) {
  const key = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      event.stopPropagation()
      onActivate()
    }
  }
  return <g role="button" tabIndex={0} aria-label={label} data-forest-interactive="true" className={`kt-action ${className}`} transform={transform} onFocus={onFocus} onKeyDown={key} onClick={event => { event.stopPropagation(); event.currentTarget.focus(); onActivate() }}>
    {children}
  </g>
}
