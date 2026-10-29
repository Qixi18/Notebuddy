import { memo, useId } from 'react'
import type { Limb } from './naturalBranchGeometry'

export const NaturalBranchWood = memo(function NaturalBranchWood({ limb, textureId, stock = false, primaryParent }: { limb: Limb; textureId: string; stock?: boolean; primaryParent?: string }) {
  const clip = `natural-limb-${useId().replace(/:/g, '')}`
  return <g className={`home-natural-limb home-natural-limb-${limb.level}`} data-wood-notebook-id={limb.bookId} aria-hidden="true" pointerEvents="none"
    data-growth-limb={limb.id} data-growth-book={limb.bookId} data-growth-note={limb.level === 3 ? limb.id.replace(/:twig$/, '') : undefined}
    data-growth-path={limb.centerPath} data-growth-radius={limb.rootRadius} data-growth-level={stock ? 0 : limb.level} data-growth-parent={primaryParent ?? limb.parentId ?? undefined} data-growth-parent-t={primaryParent ? 1 : limb.parentT}>
    <defs><clipPath id={clip}><path d={limb.outline} /></clipPath></defs>
    <path d={limb.outline} fill={`url(#${textureId}-wood)`} stroke="#796e56" strokeWidth=".4" />
    <g clipPath={`url(#${clip})`} opacity={limb.level === 3 ? .5 : .88}>
      {limb.textureSpans.map((span, index) => <g key={index} transform={`translate(${span.center.x},${span.center.y}) rotate(${span.angle})`}>
        <rect x={-span.width / 2} y={-span.length / 2} width={span.width} height={span.length} fill={`url(#${textureId}-bark)`} mask={`url(#${textureId}-bark-edge)`} />
      </g>)}
    </g>
    {limb.grain.map((path, index) => <path key={index} d={path} fill="none" stroke={index % 2 ? '#d8c89d' : '#625b45'} strokeWidth={index % 2 ? .9 : .6} strokeLinecap="round" opacity=".32" />)}
  </g>
})
