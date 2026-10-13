/**
 * 悬浮答疑坞的宽度规则与本地持久化。
 *
 * 抽成纯函数是为了脱离 DOM 单测：拖拽过程中每一帧都要重新夹一次宽度，
 * 规则一旦写死在组件里，边界值（太窄 / 太宽 / localStorage 脏数据）就失去回归。
 */

/** 默认宽度。比原固定 300px 略宽，字号调大后每行能多放几个字。 */
export const DOCK_WIDTH_DEFAULT = 340
/** 拖拽下限：再窄正文换行会明显变差。 */
export const DOCK_WIDTH_MIN = 280
/** 松手时若窄于此值，视为「我想关掉它」，直接收合。 */
export const DOCK_WIDTH_SNAP = 200
/** 上限比例：抽屉最多占外壳总宽的 72%，保证正文始终有位置。 */
export const DOCK_WIDTH_MAX_RATIO = 0.72
/** 键盘方向键每次调整的步长。 */
export const DOCK_WIDTH_STEP = 24

export const DOCK_STORAGE = {
  open: 'notebuddy.dock-open',
  width: 'notebuddy.dock-width',
} as const

/**
 * 把宽度夹进 [MIN, 外壳宽度 × 72%]。
 * containerWidth 传外壳（侧边栏 + 正文 + 抽屉）总宽；拿不到有效值时只做下限保护。
 */
export function clampDockWidth(width: number, containerWidth: number): number {
  const rounded = Math.round(width)
  if (!Number.isFinite(rounded)) return DOCK_WIDTH_DEFAULT
  const usable = Number.isFinite(containerWidth) && containerWidth > 0 ? containerWidth : 0
  const max = Math.max(DOCK_WIDTH_MIN, Math.round(usable * DOCK_WIDTH_MAX_RATIO))
  return Math.min(Math.max(rounded, DOCK_WIDTH_MIN), max)
}

/** 读取持久化宽度。缺失或损坏时回退默认值；上限留到拖拽时按实际容器再夹。 */
export function resolveDockWidth(raw: string | null): number {
  const parsed = Number.parseInt(raw ?? '', 10)
  if (!Number.isFinite(parsed) || parsed <= 0) return DOCK_WIDTH_DEFAULT
  return Math.max(parsed, DOCK_WIDTH_MIN)
}

/**
 * 读取持久化的开合状态。未记录时默认收起 —— 悬浮球是入口，
 * 首屏把宽度让给正文，由用户主动唤起助手（参考项目的抽屉同此约定）。
 */
export function resolveDockOpen(raw: string | null): boolean {
  return raw === 'true'
}
