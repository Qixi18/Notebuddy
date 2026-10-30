import { cleanup } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import {
  PET_DOCK_VISIBLE,
  PET_SIZE_DEFAULT,
  PET_SIZE_MAX,
  PET_SIZE_MIN,
  PET_SIZE_PRESETS,
  clampPetSize,
  clampToViewport,
  defaultFloatPoint,
  dockedOffset,
  nearestEdge,
  petBoxSize,
  pointToRatio,
  ratioToPoint,
} from '../src/features/pet/petLayout'
import { PET_STORAGE_KEY, loadPetPlacement, savePetPlacement, savePetSize } from '../src/features/pet/petStorage'

afterEach(cleanup)

const SIZE = petBoxSize(PET_SIZE_DEFAULT)
const VIEW = { width: 1440, height: 900 }

function fakeStorage() {
  const store = new Map<string, string>()
  return {
    store,
    storage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value) },
    } as Storage,
  }
}

test('几何：clamp、贴边判定、吸附平移、比例换算', () => {
  expect(clampToViewport({ x: -20, y: 2000 }, SIZE, VIEW)).toEqual({ x: 8, y: 900 - SIZE.height - 8 })
  expect(nearestEdge({ x: 10, y: 300 }, SIZE, VIEW)).toBe('left')
  expect(nearestEdge({ x: 1300, y: 300 }, SIZE, VIEW)).toBe('right')
  expect(nearestEdge({ x: 600, y: 860 }, SIZE, VIEW)).toBe('bottom')
  expect(nearestEdge({ x: 600, y: 300 }, SIZE, VIEW)).toBeNull()
  expect(dockedOffset('right', SIZE)).toEqual({ x: SIZE.width - PET_DOCK_VISIBLE, y: 0 })

  const point = { x: 700, y: 320 }
  const ratio = pointToRatio(point, VIEW, SIZE)
  const restored = ratioToPoint(ratio, SIZE, VIEW)
  expect(Math.abs(restored.x - point.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(restored.y - point.y)).toBeLessThanOrEqual(1)
  expect(defaultFloatPoint(SIZE, VIEW)).toEqual(clampToViewport(
    { x: VIEW.width - SIZE.width - 36, y: VIEW.height - SIZE.height - 170 },
    SIZE, VIEW,
  ))
})

test('尺寸：高度夹紧、宽度按 408×544 换算，栏内与浮层同一比例', () => {
  expect(petBoxSize(PET_SIZE_DEFAULT)).toEqual({
    width: Math.round(PET_SIZE_DEFAULT * 408 / 544),
    height: PET_SIZE_DEFAULT,
  })
  expect(petBoxSize(10).height).toBe(PET_SIZE_MIN)
  expect(petBoxSize(9999).height).toBe(PET_SIZE_MAX)
  expect(clampPetSize(Number.NaN)).toBe(PET_SIZE_DEFAULT)
  // 三档预设都在可调范围内，且默认档就在菜单里
  for (const preset of PET_SIZE_PRESETS) {
    expect(preset.height).toBeGreaterThanOrEqual(PET_SIZE_MIN)
    expect(preset.height).toBeLessThanOrEqual(PET_SIZE_MAX)
  }
  expect(PET_SIZE_PRESETS.some((preset) => preset.height === PET_SIZE_DEFAULT)).toBe(true)
})

test('petStorage：读写往返，脏数据回退 null', () => {
  const { store, storage } = fakeStorage()
  expect(loadPetPlacement(storage)).toBeNull()
  savePetPlacement({ version: 1, mode: 'float', xRatio: 0.8, yRatio: 0.4 }, storage)
  expect(store.get(PET_STORAGE_KEY)).toBeTruthy()
  expect(loadPetPlacement(storage)).toEqual({ version: 1, mode: 'float', xRatio: 0.8, yRatio: 0.4 })

  store.set(PET_STORAGE_KEY, '{broken json')
  expect(loadPetPlacement(storage)).toBeNull()
  store.set(PET_STORAGE_KEY, JSON.stringify({ mode: 'weird', xRatio: 'abc', yRatio: 2 }))
  expect(loadPetPlacement(storage)).toBeNull()
  store.set(PET_STORAGE_KEY, JSON.stringify({ mode: 42, xRatio: 0.5, yRatio: 1.7 }))
  const clamped = loadPetPlacement(storage)
  expect(clamped?.mode).toBe('rail') // 非法 mode 回退 rail
  expect(clamped?.yRatio).toBe(1) // 越界比例收紧
})

test('petStorage：大小独立保存，不动既有形态与位置', () => {
  const { storage } = fakeStorage()
  savePetPlacement({ version: 1, mode: 'float', xRatio: 0.8, yRatio: 0.4, size: PET_SIZE_DEFAULT }, storage)
  savePetSize(208, storage)
  expect(loadPetPlacement(storage)).toEqual({ version: 1, mode: 'float', xRatio: 0.8, yRatio: 0.4, size: 208 })

  // 越界高度被夹住，脏值回退默认
  savePetSize(9999, storage)
  expect(loadPetPlacement(storage)?.size).toBe(PET_SIZE_MAX)
  savePetSize(Number.NaN, storage)
  expect(loadPetPlacement(storage)?.size).toBe(PET_SIZE_DEFAULT)
})
