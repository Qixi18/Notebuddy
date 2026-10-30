/** Intersect the browser viewport and actual clipping ancestors, including the forest SVG. */
export function growthVisible(element: Element): boolean {
  const rect = element.getBoundingClientRect()
  if (!(rect.width > 0 && rect.height > 0)) return false
  let left = Math.max(0, rect.left), right = Math.min(innerWidth, rect.right)
  let top = Math.max(0, rect.top), bottom = Math.min(innerHeight, rect.bottom)
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const style = getComputedStyle(parent)
    const svgClip = parent instanceof SVGSVGElement && style.overflow !== 'visible'
    const clipX = svgClip || /hidden|clip|scroll|auto/.test(style.overflowX || style.overflow)
    const clipY = svgClip || /hidden|clip|scroll|auto/.test(style.overflowY || style.overflow)
    if (!clipX && !clipY) continue
    const bounds = parent.getBoundingClientRect()
    if (clipX) { left = Math.max(left, bounds.left); right = Math.min(right, bounds.right) }
    if (clipY) { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom) }
  }
  return right > left && bottom > top
}
