import {
  PET_BOUNCE_MIN_SPEED,
  PET_FLING_FRICTION,
  PET_FLING_STOP_SPEED,
  PET_VELOCITY_MIN_SAMPLES,
  PET_VELOCITY_WINDOW_MS,
  clampToViewport,
  type PetPoint,
  type PetSize,
  type PetViewport,
} from './petLayout'

/**
 * 甩抛物理：速度采样与惯性积分都是纯函数，方便单测。
 * 采样窗口 120ms、摩擦按 60fps 基准换算、低速撞边直接停（不反弹）。
 */

export type Velocity = { vx: number; vy: number }
export type FlingState = PetPoint & Velocity
export type FlingStepResult = { state: FlingState; done: boolean }

type Sample = { x: number; y: number; t: number }

export class FlingTracker {
  private samples: Sample[] = []

  reset(): void {
    this.samples = []
  }

  push(x: number, y: number, t: number = Date.now()): void {
    this.samples.push({ x, y, t })
    const newest = this.samples[this.samples.length - 1].t
    while (this.samples.length > 1 && newest - this.samples[0].t > PET_VELOCITY_WINDOW_MS) {
      this.samples.shift()
    }
  }

  /** 窗口内首尾样本的均速度（px/s）；样本不足返回 null */
  velocity(): Velocity | null {
    if (this.samples.length < PET_VELOCITY_MIN_SAMPLES) return null
    const first = this.samples[0]
    const last = this.samples[this.samples.length - 1]
    const dt = (last.t - first.t) / 1000
    if (dt <= 0) return null
    return { vx: (last.x - first.x) / dt, vy: (last.y - first.y) / dt }
  }
}

export function speedOf(velocity: Velocity): number {
  return Math.hypot(velocity.vx, velocity.vy)
}

/** 惯性推进一帧；dt 为秒。返回 done=true 表示可以停下了 */
export function stepFling(state: FlingState, dt: number, size: PetSize, viewport: PetViewport): FlingStepResult {
  const safeDt = Number.isFinite(dt) && dt > 0 ? Math.min(dt, 0.05) : 1 / 60
  const decay = Math.pow(PET_FLING_FRICTION, safeDt * 60)
  let { x, y, vx, vy } = state
  vx *= decay
  vy *= decay
  x += vx * safeDt
  y += vy * safeDt

  const margin = 8
  const maxX = Math.max(margin, viewport.width - size.width - margin)
  const maxY = Math.max(margin, viewport.height - size.height - margin)
  if (x < margin) {
    x = margin
    if (Math.abs(vx) > PET_BOUNCE_MIN_SPEED) vx = -vx * 0.6
    else vx = 0
  } else if (x > maxX) {
    x = maxX
    if (Math.abs(vx) > PET_BOUNCE_MIN_SPEED) vx = -vx * 0.6
    else vx = 0
  }
  if (y < margin) {
    y = margin
    if (Math.abs(vy) > PET_BOUNCE_MIN_SPEED) vy = -vy * 0.6
    else vy = 0
  } else if (y > maxY) {
    y = maxY
    if (Math.abs(vy) > PET_BOUNCE_MIN_SPEED) vy = -vy * 0.6
    else vy = 0
  }

  const done = speedOf({ vx, vy }) < PET_FLING_STOP_SPEED
  const next = { x, y, vx: done ? 0 : vx, vy: done ? 0 : vy }
  return { state: { ...next, ...clampToViewport(next, size, viewport) }, done }
}
