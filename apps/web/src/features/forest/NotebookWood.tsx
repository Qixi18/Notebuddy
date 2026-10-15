import { memo, useId, useMemo } from 'react'
import { branchWood } from './branchWood'
import type { KnowledgeLeaf, NotebookGeometry } from './treeGeometry'

export const NotebookWood = memo(function NotebookWood({ branch, leaves, textureId }: { branch: NotebookGeometry; leaves: KnowledgeLeaf[]; textureId: string }) {
  const wood = useMemo(() => branchWood(branch, leaves), [branch, leaves])
  const clipId = `limb-${useId().replace(/:/g, '')}`
  return <g className="kt-branch-wood" aria-hidden="true" pointerEvents="none">
    <defs><clipPath id={clipId}><path d={wood.outline} /></clipPath></defs>
    <path d={wood.outline} fill={`url(#${textureId}-wood)`} stroke="#796e56" strokeWidth=".6" />
    <g clipPath={`url(#${clipId})`} opacity=".9">
      {wood.textureSpans.map((span, i) => <g key={i} transform={`translate(${span.center.x},${span.center.y}) rotate(${span.angle})`}>
        <rect x="-21" y={-span.length / 2} width="42" height={span.length} fill={`url(#${textureId}-bark)`} mask={`url(#${textureId}-bark-edge)`} />
      </g>)}
    </g>
    <path d={wood.bark.filter((_, i) => i % 2 === 0).join(' ')} fill="none" stroke="#625b45" strokeWidth=".8" strokeLinecap="round" opacity=".2" />
    <path d={wood.bark.filter((_, i) => i % 2 !== 0).join(' ')} fill="none" stroke="#dbca9d" strokeWidth="1.2" strokeLinecap="round" opacity=".24" />
    {wood.twigs.map(twig => <path key={twig.noteId} d={twig.path} fill="none" stroke="#8b7959" strokeWidth="1.55" strokeLinecap="round" />)}
  </g>
})
