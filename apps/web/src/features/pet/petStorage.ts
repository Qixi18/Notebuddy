import { clamp, clampPetSize, type PetMode, type PetRatio } from './petLayout'

/**
 * 桌宠形态、浮层位置与大小的本地记忆。
 * localStorage['notebuddy.pet.pos'] = { version, mode, xRatio, yRatio, size }。
 * 数据一律校验后使用，脏数据回退 null（调用方按「栏内 + 默认位置 / 默认大小」处理）。
 */

export const PET_STORAGE_KEY = 'notebuddy.pet.pos'

export type PetPlacement = PetRatio & { version: 1; mode: PetMode; size?: number }

function parseRatio(value: unknown): number | null {
  const num = typeof value === 'string' ? Number(value) : value
  return typeof num === 'number' && Number.isFinite(num) ? clamp(num, 0, 1) : null
}

export function loadPetPlacement(store: Storage | null = safeLocalStorage()): PetPlacement | null {
  if (!store) return null
  try {
    const raw = store.getItem(PET_STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as Record<string, unknown>
    const mode: PetMode = data.mode === 'float' ? 'float' : 'rail'
    const xRatio = parseRatio(data.xRatio)
    const yRatio = parseRatio(data.yRatio)
    if (xRatio === null || yRatio === null) return null
    const size = typeof data.size === 'number' && Number.isFinite(data.size) ? clampPetSize(data.size) : undefined
    return { version: 1, mode, xRatio, yRatio, ...(size === undefined ? {} : { size }) }
  } catch {
    return null
  }
}

export function savePetPlacement(placement: PetPlacement, store: Storage | null = safeLocalStorage()): void {
  if (!store) return
  try {
    store.setItem(PET_STORAGE_KEY, JSON.stringify({ ...placement, version: 1 as const }))
  } catch {
    /* 隐私模式等写入失败时静默放弃：位置记忆是增强能力，不该打断主流程 */
  }
}

/**
 * 只改大小，保留既有的形态与位置。
 * 旧数据（无 size 字段）也兼容：缺失时按当前默认比例补一个中性位置。
 */
export function savePetSize(size: number, store: Storage | null = safeLocalStorage()): void {
  const current = loadPetPlacement(store)
  savePetPlacement({
    version: 1,
    mode: current?.mode ?? 'rail',
    xRatio: current?.xRatio ?? 0.5,
    yRatio: current?.yRatio ?? 0.5,
    size: clampPetSize(size),
  }, store)
}

function safeLocalStorage(): Storage | null {
  try {
    if (typeof localStorage === 'undefined') return null
    return localStorage
  } catch {
    return null
  }
}
