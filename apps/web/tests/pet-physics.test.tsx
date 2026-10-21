import { cleanup } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import { FlingTracker, speedOf, stepFling } from '../src/features/pet/petPhysics'
import {
  PET_DOCK_VISIBLE,
  PET_FLOAT_SIZE,
  clampToViewport,
  defaultFloatPoint,
  dockedOffset,
  nearestEdge,
  pointToRatio,
  ratioToPoint,
} from '../src/features/pet/petLayout'
import { PET_STORAGE_KEY, loadPetPlacement, savePetPlacement } from '../src/features/pet/petStorage'

afterEach(cleanup)

const SIZE = { width: PET_FLOAT_SIZE, height: PET_FLOAT_SIZE }
const VIEW = { width: 1440, height: 900 }

test('FlingTracker：120ms 窗口内采样估算 px/s，样本不足返回 null', () => {
  const tracker = new FlingTracker()
  expect(tracker.velocity()).toBeNull()
  tracker.push(0, 0, 1000)
  expect(tracker.velocity()).toBeNull() // 只有 1 个样本
  tracker.push(30, 40, 1040)
  tracker.push(90, 120, 1100)
  const velocity = tracker.velocity()
  expect(velocity).not.toBeNull()
  expect(speedOf(velocity!)).toBeCloseTo(Math.hypot(90, 120) / 0.1, 0) // 1500 px/s
})

test('FlingTracker：窗口外的旧样本被丢弃，不影响速度估算', () => {
  const tracker = new FlingTracker()
  tracker.push(0, 0, 0)
  tracker.push(100, 0, 1000) // 与下一采样的间隔把 t=0 挤出 120ms 窗口
  tracker.push(110, 0, 1060)
  tracker.push(170, 0, 1120) // 1120-1000 = 120，恰好在窗口内
  const velocity = tracker.velocity()
  expect(velocity?.vx).toBeCloseTo(70 / 0.12, 5) // 只用窗口内首尾两点
})

test('stepFling：摩擦衰减，速度低于阈值停止', () => {
  let state = { x: 200, y: 200, vx: 600, vy: 0 }
  let frames = 0
  while (frames < 600) {
    const result = stepFling(state, 1 / 60, SIZE, VIEW)
    state = result.state
    frames++
    if (result.done) break
  }
  expect(frames).toBeLessThan(600)
  expect(speedOf(state)).toBeLessThan(34)
  expect(state.vx).toBe(0)
})

test('stepFling：高速撞边反弹，低速贴边停止，位置不出界', () => {
  const bounced = stepFling({ x: 1430, y: 100, vx: -0, vy: 0 }, 1 / 60, SIZE, VIEW)
  expect(bounced.state.x).toBeLessThanOrEqual(1440 - PET_FLOAT_SIZE - 8)

  let state = { x: 1432, y: 100, vx: 300, vy: 0 }
  state = stepFling(state, 1 / 60, SIZE, VIEW).state
  expect(state.x).toBeLessThanOrEqual(1440 - PET_FLOAT_SIZE - 8)
  expect(state.vx).toBeLessThan(0) // 高速入射反弹

  const stopped = stepFling({ x: 1432, y: 100, vx: 50, vy: 0 }, 1 / 60, SIZE, VIEW)
  expect(stopped.state.vx).toBe(0) // 低速撞边直接停
})

test('几何：clamp、贴边判定、吸附平移、比例换算', () => {
  expect(clampToViewport({ x: -20, y: 2000 }, SIZE, VIEW)).toEqual({ x: 8, y: 900 - PET_FLOAT_SIZE - 8 })
  expect(nearestEdge({ x: 10, y: 300 }, SIZE, VIEW)).toBe('left')
  expect(nearestEdge({ x: 1300, y: 300 }, SIZE, VIEW)).toBe('right')
  expect(nearestEdge({ x: 600, y: 860 }, SIZE, VIEW)).toBe('bottom')
  expect(nearestEdge({ x: 600, y: 300 }, SIZE, VIEW)).toBeNull()
  expect(dockedOffset('right', SIZE)).toEqual({ x: PET_FLOAT_SIZE - PET_DOCK_VISIBLE, y: 0 })

  const point = { x: 700, y: 320 }
  const ratio = pointToRatio(point, VIEW)
  const restored = ratioToPoint(ratio, SIZE, VIEW)
  expect(Math.abs(restored.x - point.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(restored.y - point.y)).toBeLessThanOrEqual(1)
  expect(defaultFloatPoint(SIZE, VIEW)).toEqual(clampToViewport(
    { x: VIEW.width - PET_FLOAT_SIZE - 36, y: VIEW.height - PET_FLOAT_SIZE - 170 },
    SIZE, VIEW,
  ))
})

test('petStorage：读写往返，脏数据回退 null', () => {
  const store = new Map<string, string>()
  const fakeStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value) },
  }
  expect(loadPetPlacement(fakeStorage as Storage)).toBeNull()
  savePetPlacement({ version: 1, mode: 'float', xRatio: 0.8, yRatio: 0.4 }, fakeStorage as Storage)
  expect(store.get(PET_STORAGE_KEY)).toBeTruthy()
  const placement = loadPetPlacement(fakeStorage as Storage)
  expect(placement).toEqual({ version: 1, mode: 'float', xRatio: 0.8, yRatio: 0.4 })

  store.set(PET_STORAGE_KEY, '{broken json')
  expect(loadPetPlacement(fakeStorage as Storage)).toBeNull()
  store.set(PET_STORAGE_KEY, JSON.stringify({ mode: 'weird', xRatio: 'abc', yRatio: 2 }))
  expect(loadPetPlacement(fakeStorage as Storage)).toBeNull()
  store.set(PET_STORAGE_KEY, JSON.stringify({ mode: 42, xRatio: 0.5, yRatio: 1.7 }))
  const clamped = loadPetPlacement(fakeStorage as Storage)
  expect(clamped?.mode).toBe('rail') // 非法 mode 回退 rail
  expect(clamped?.yRatio).toBe(1) // 越界比例收紧
})
