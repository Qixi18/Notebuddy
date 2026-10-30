import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { resetEggs, reportQuestion, type PetEggCommand } from '../src/features/pet/petEggs'
import { usePetEasterEggs } from '../src/features/pet/usePetEasterEggs'

/**
 * 彩蛋触发器的约束：
 * - 连点 8 下（3s 内）→ poke；慢点不触发
 * - 10 分钟内重问同一句 → repeat；超过窗口 / 换了句子不触发
 * - 凌晨打开页面 → night
 * - 草稿停笔 30s → drafting；草稿一变就重新计时
 * - 离开 ≥60s 回来 → return
 * - 每个彩蛋每会话只放一次；忙的时候先挂起，这轮结束再放
 */

let latest: PetEggCommand | null = null
let clicks: Array<() => void> = []

function Harness({ busy = false, draft = '' }: { busy?: boolean; draft?: string }) {
  const { command, noteClick } = usePetEasterEggs({ busy, draft })
  latest = command
  clicks.push(noteClick)
  return null
}

const poke = () => act(() => { for (let i = 0; i < 8; i += 1) clicks[clicks.length - 1]() })

beforeEach(() => {
  resetEggs()
  latest = null
  clicks = []
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-28T14:00:00'))
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

test('连点：3 秒内点 8 下才触发，慢点不触发', () => {
  render(<Harness />)
  poke()
  expect(latest?.id).toBe('poke')
  expect(latest?.bubble).toContain('不是门铃')
})

test('连点：分散在 3 秒之外不算', () => {
  render(<Harness />)
  for (let i = 0; i < 8; i += 1) {
    act(() => { clicks[clicks.length - 1]() })
    act(() => { vi.advanceTimersByTime(600) })
  }
  expect(latest).toBeNull()
})

test('重问：10 分钟内同一句触发一次', () => {
  render(<Harness />)
  act(() => { reportQuestion('余弦定理怎么推的？') })
  expect(latest).toBeNull()

  act(() => { vi.advanceTimersByTime(60_000) })
  act(() => { reportQuestion('余弦定理怎么推的？') })
  expect(latest?.id).toBe('repeat')
})

test('重问：换了句子或超过 10 分钟都不算', () => {
  render(<Harness />)
  act(() => { reportQuestion('第一个问题') })
  act(() => { reportQuestion('第二个问题') })
  expect(latest).toBeNull()

  act(() => { vi.advanceTimersByTime(11 * 60_000) })
  act(() => { reportQuestion('第二个问题') })
  expect(latest).toBeNull()
})

test('夜场：凌晨打开才触发', () => {
  vi.setSystemTime(new Date('2026-10-29T02:30:00'))
  render(<Harness />)
  act(() => { vi.advanceTimersByTime(2600) })
  expect(latest?.id).toBe('night')

  resetEggs()
  latest = null
  vi.setSystemTime(new Date('2026-10-29T14:30:00'))
  render(<Harness />)
  act(() => { vi.advanceTimersByTime(2600) })
  expect(latest).toBeNull()
})

test('停笔：草稿留在框里 30s 才提示，改字就重新计时', () => {
  const view = render(<Harness draft="" />)
  act(() => { vi.advanceTimersByTime(40_000) })
  expect(latest).toBeNull() // 空草稿不触发

  view.rerender(<Harness draft="这道题" />)
  act(() => { vi.advanceTimersByTime(20_000) })
  expect(latest).toBeNull()

  view.rerender(<Harness draft="这道题怎么" />) // 改字重置
  act(() => { vi.advanceTimersByTime(29_000) })
  expect(latest).toBeNull()

  act(() => { vi.advanceTimersByTime(1500) })
  expect(latest?.id).toBe('drafting')
})

test('离开归来：≥60s 才打招呼', () => {
  render(<Harness />)
  act(() => { window.dispatchEvent(new Event('blur')) })
  act(() => { vi.advanceTimersByTime(30_000) })
  act(() => { window.dispatchEvent(new Event('focus')) })
  expect(latest).toBeNull() // 离开太短

  act(() => { window.dispatchEvent(new Event('blur')) })
  act(() => { vi.advanceTimersByTime(61_000) })
  act(() => { window.dispatchEvent(new Event('focus')) })
  expect(latest?.id).toBe('return')
})

test('每个彩蛋每会话只放一次', () => {
  render(<Harness />)
  poke()
  expect(latest?.id).toBe('poke')
  const first = latest
  poke()
  expect(latest).toBe(first) // 第二次不再产生新命令
})

test('忙的时候先挂起，这轮结束再放', () => {
  const view = render(<Harness busy />)
  poke()
  expect(latest).toBeNull() // 思考中不打断

  view.rerender(<Harness busy={false} />)
  expect(latest?.id).toBe('poke')
})
