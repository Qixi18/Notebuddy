import { cleanup } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

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
