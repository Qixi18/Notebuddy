/**
 * 页内桌宠浮层的常量与几何换算。
 * 数值沿用 docs/design/2026-10-20-assistant-pet-optimization.md 第四节的行为约定
 * （阈值参考 dsh-whale-girl，学习场景下调了吸附范围）。
 */

export const PET_FLOAT_SIZE = 120
/** 位移低于该值按点击处理，不进入拖拽 */
export const PET_DRAG_THRESHOLD = 6
/** 松手速度采样窗口 */
export const PET_VELOCITY_WINDOW_MS = 120
export const PET_VELOCITY_MIN_SAMPLES = 3
/** 超过该速度（px/s）进入惯性甩抛 */
export const PET_FLING_SPEED = 800
/** 每帧（60fps 基准）速度保留比例 */
export const PET_FLING_FRICTION = 0.985
/** 低于该速度（px/s）惯性停止 */
export const PET_FLING_STOP_SPEED = 34
/** 低速撞边直接停，不反弹，避免贴边抖动 */
export const PET_BOUNCE_MIN_SPEED = 120
/** 距边缘小于该值吸附半隐藏 */
export const PET_SNAP_RANGE = 56
/** 吸附后立绘露出的宽度 */
export const PET_DOCK_VISIBLE = 48
/** 浮层与视口的最小边距 */
export const PET_VIEWPORT_MARGIN = 8
/** 键盘方向键每次移动距离 */
export const PET_KEY_STEP = 8
/** 悬浮球之外，本阶段只有 栏内 / 浮层 两种形态 */
export type PetMode = 'rail' | 'float'
export type PetEdge = 'left' | 'right' | 'bottom'
export type PetPoint = { x: number; y: number }
export type PetSize = { width: number; height: number }
export type PetViewport = { width: number; height: number }
export type PetRatio = { xRatio: number; yRatio: number }

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min
  return Math.min(Math.max(value, min), max)
}

export function clampToViewport(point: PetPoint, size: PetSize, viewport: PetViewport): PetPoint {
  const maxX = Math.max(PET_VIEWPORT_MARGIN, viewport.width - size.width - PET_VIEWPORT_MARGIN)
  const maxY = Math.max(PET_VIEWPORT_MARGIN, viewport.height - size.height - PET_VIEWPORT_MARGIN)
  return {
    x: clamp(point.x, PET_VIEWPORT_MARGIN, maxX),
    y: clamp(point.y, PET_VIEWPORT_MARGIN, maxY),
  }
}

export function pointToRatio(point: PetPoint, viewport: PetViewport): PetRatio {
  const width = Math.max(1, viewport.width - sizeReserve(viewport.width))
  const height = Math.max(1, viewport.height - sizeReserve(viewport.height))
  return {
    xRatio: clamp(point.x / width, 0, 1),
    yRatio: clamp(point.y / height, 0, 1),
  }
}

export function ratioToPoint(ratio: PetRatio, size: PetSize, viewport: PetViewport): PetPoint {
  const width = Math.max(1, viewport.width - sizeReserve(viewport.width))
  const height = Math.max(1, viewport.height - sizeReserve(viewport.height))
  return clampToViewport({ x: ratio.xRatio * width, y: ratio.yRatio * height }, size, viewport)
}

function sizeReserve(viewportLength: number): number {
  // 比例换算时给浮层自身和边距留出空间，避免贴边比值算出 1 之后越界
  return Math.min(PET_FLOAT_SIZE + PET_VIEWPORT_MARGIN * 2, Math.max(0, viewportLength - 1))
}

/** 距左右/下边缘的最近吸附边；范围外或贴上边缘返回 null */
export function nearestEdge(point: PetPoint, size: PetSize, viewport: PetViewport, range = PET_SNAP_RANGE): PetEdge | null {
  const distances: Array<{ edge: PetEdge; distance: number }> = [
    { edge: 'left', distance: point.x },
    { edge: 'right', distance: viewport.width - (point.x + size.width) },
    { edge: 'bottom', distance: viewport.height - (point.y + size.height) },
  ]
  const nearest = distances.reduce((best, item) => (item.distance < best.distance ? item : best))
  return nearest.distance <= range ? nearest.edge : null
}

/** 吸附半隐藏时内层元素的平移量（外层仍停在 clamp 后的位置） */
export function dockedOffset(edge: PetEdge, size: PetSize): PetPoint {
  const hide = Math.max(0, size.width - PET_DOCK_VISIBLE)
  switch (edge) {
    case 'left': return { x: -hide, y: 0 }
    case 'right': return { x: hide, y: 0 }
    case 'bottom': return { x: 0, y: hide }
  }
}

/** 无记忆位置时的默认落点：右下角、输入区上方 */
export function defaultFloatPoint(size: PetSize, viewport: PetViewport): PetPoint {
  return clampToViewport(
    { x: viewport.width - size.width - 36, y: viewport.height - size.height - 170 },
    size,
    viewport,
  )
}
