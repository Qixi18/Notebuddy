import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  clampDockWidth,
  resolveDockOpen,
  resolveDockWidth,
  DOCK_WIDTH_DEFAULT,
  DOCK_WIDTH_MIN,
} from '../src/features/assistant/dockLayout.ts'

test('宽度既不低于下限，也不超过外壳总宽的 72%', () => {
  assert.equal(clampDockWidth(500, 1000), 500)
  assert.equal(clampDockWidth(1200, 1000), 720)
  assert.equal(clampDockWidth(100, 1000), DOCK_WIDTH_MIN)
})

test('拿不到容器宽度时只做下限保护，不会把抽屉算成 0', () => {
  assert.equal(clampDockWidth(500, 0), DOCK_WIDTH_MIN)
  assert.equal(clampDockWidth(500, Number.NaN), DOCK_WIDTH_MIN)
  assert.equal(clampDockWidth(Number.NaN, 1000), DOCK_WIDTH_DEFAULT)
})

test('localStorage 里的脏数据一律回退默认值', () => {
  assert.equal(resolveDockWidth(null), DOCK_WIDTH_DEFAULT)
  assert.equal(resolveDockWidth(''), DOCK_WIDTH_DEFAULT)
  assert.equal(resolveDockWidth('abc'), DOCK_WIDTH_DEFAULT)
  assert.equal(resolveDockWidth('-40'), DOCK_WIDTH_DEFAULT)
  assert.equal(resolveDockWidth('0'), DOCK_WIDTH_DEFAULT)
})

test('偏小的历史宽度被托到下限，正常值原样沿用', () => {
  assert.equal(resolveDockWidth('90'), DOCK_WIDTH_MIN)
  assert.equal(resolveDockWidth('460'), 460)
})

test('未记录开合状态时默认收起，只有明确的 true 才算展开', () => {
  assert.equal(resolveDockOpen(null), false)
  assert.equal(resolveDockOpen('1'), false)
  assert.equal(resolveDockOpen('false'), false)
  assert.equal(resolveDockOpen('true'), true)
})
