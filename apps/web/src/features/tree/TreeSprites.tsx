// Crop the alpha atlases using nested SVG viewboxes; never stretch a whole tree
// bitmap over business nodes. Labels and hit targets are rendered separately.
export function TrunkSprite({ variant, empty = false }: { variant: number; empty?: boolean }) {
  // Connected-component QA found that roots cross nominal 418px columns. These
  // isolated bounds retain the complete roots without borrowing the next trunk.
  const crops = ['20 70 440 1130', '460 70 440 1130', '892 70 440 1130']
  const height = empty ? 330 : 490
  const width = empty ? 136 : 198
  return <svg x={-width / 2} y={-height + 16} width={width} height={height} viewBox={crops[variant % 3]} preserveAspectRatio="none" overflow="hidden" aria-hidden="true">
    <image href="/assets/forest/trunks-atlas.webp" width="1254" height="1254" />
  </svg>
}

/** Redrawn lower stocks; the existing procedural crown remains unchanged. */
export function RootstockSprite({ variant }: { variant: number }) {
  const crops = ['30 35 665 735', '695 35 665 735', '1360 35 639 735']
  const offsets = [-24, -8, -14]
  const index = variant % 3
  return <svg x={-112 + offsets[index]} y="-248" width="224" height="265" viewBox={crops[index]} preserveAspectRatio="none" overflow="hidden" aria-hidden="true">
    <image href="/assets/forest/rootstocks-v2.png" width="1999" height="787" />
  </svg>
}
export function LeafSprite({ variant, angle = 0 }: { variant: number; angle?: number }) {
  return <g transform={`rotate(${angle})`} aria-hidden="true" pointerEvents="none">
    <svg x="-23" y="-65" width="46" height="69" viewBox={`${(variant % 3) * 418} ${Math.floor(variant / 3) * 627} 418 627`} preserveAspectRatio="none" overflow="hidden">
      <image href="/assets/forest/leaves-atlas.webp" width="1254" height="1254" />
    </svg>
  </g>
}
