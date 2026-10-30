import { saplingGeometry } from './saplingGeometry'

const crowns = [0, 1, 2].map(saplingGeometry)

export function SaplingCrown({ variant, textureId }: { variant: number; textureId: string }) {
  return <g className="kt-sapling-crown" aria-hidden="true" pointerEvents="none">
    {crowns[variant % 3].map((branch, index) => <g key={index} className="kt-sapling-bough">
      <g data-growth-sapling-path={branch.spine}><path d={branch.outline} fill={`url(#${textureId}-wood)`} stroke="#887859" strokeWidth=".5" />
      <path d={branch.outline} fill={`url(#${textureId}-bark)`} opacity=".42" />
      <path className="kt-sapling-spine" d={branch.spine} fill="none" stroke="#d8c69b" strokeWidth=".65" opacity=".65" /></g>
      <g data-growth-sapling-foliage="true">{branch.foliage.map((leaf, leafIndex) => <g key={leafIndex} className="kt-sapling-sprig">
        <path className="kt-sapling-twig" d={leaf.path} fill="none" stroke="#8a7957" strokeWidth="1.1" strokeLinecap="round" />
      </g>)}</g>
    </g>)}
  </g>
}
