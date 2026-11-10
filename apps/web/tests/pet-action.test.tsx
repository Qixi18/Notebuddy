import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import type { TeacherStatus } from '../src/components/TeacherCharacter'
import { usePetAction } from '../src/features/pet/usePetAction'

/**
 * 动作状态机的约束：
 * - 思考先正放 intro，再切 75↔22 的往复段（兜底 3.17s）
 * - 正文一开始吐字就切讲解，不等整段答案生成完
 * - 讲解正片(10s)播完还在吐字 → 接 explaining-loop 小往复
 * - 吐字结束 → 把当前这一轮播完再回待机
 * - 悬停 3s 才打招呼，且不打断正在播的动作
 */

function Harness({ status, hovered = false, streaming = false, dragging = false }: {
  status: TeacherStatus
  hovered?: boolean
  streaming?: boolean
  dragging?: boolean
}) {
  const { src } = usePetAction(status, hovered, streaming, null, dragging)
  return <img data-testid="pet" src={src} alt="" />
}

let current: ReturnType<typeof render>
const srcOf = () => current.getByTestId('pet').getAttribute('src') ?? ''

beforeEach(() => {
  vi.useFakeTimers()
  // jsdom 里没有真实后端：manifest 拉不到时走兜底时长
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))))
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

test('思考：intro 播完接往复段，长思考也不回待机', () => {
  current = render(<Harness status="idle" />)
  expect(srcOf()).toContain('idle.webp')

  current.rerender(<Harness status="thinking" />)
  expect(srcOf()).toContain('thinking-intro.webp')

  act(() => { vi.advanceTimersByTime(3200) })
  expect(srcOf()).toContain('thinking-loop.webp')

  act(() => { vi.advanceTimersByTime(30000) })
  expect(srcOf()).toContain('thinking-loop.webp')
})

test('吐字即讲解：思考中途开始输出正文，立刻切讲解', () => {
  current = render(<Harness status="thinking" />)
  act(() => { vi.advanceTimersByTime(1000) })
  expect(srcOf()).toContain('thinking-intro.webp')

  current.rerender(<Harness status="thinking" streaming />)
  expect(srcOf()).toContain('explaining.webp')

  // 状态仍是 thinking（busy），讲解不该被状态机拉回思考
  act(() => { vi.advanceTimersByTime(5000) })
  expect(srcOf()).toContain('explaining.webp')
})

test('讲解正片播完还在吐字：接小往复，不干站着', () => {
  current = render(<Harness status="thinking" streaming />)
  expect(srcOf()).toContain('explaining.webp')

  act(() => { vi.advanceTimersByTime(10100) })
  expect(srcOf()).toContain('explaining-loop.webp')

  act(() => { vi.advanceTimersByTime(20000) })
  expect(srcOf()).toContain('explaining-loop.webp') // 一直在写就一直往复
})

test('输出结束：把当前这一轮讲解播完再回待机', () => {
  current = render(<Harness status="thinking" streaming />)
  act(() => { vi.advanceTimersByTime(2000) }) // 讲解播了 2s

  // 请求结束：busy 归 false，状态变粘滞的 explaining
  current.rerender(<Harness status="explaining" />)
  expect(srcOf()).toContain('explaining.webp') // 不能立刻掐断

  act(() => { vi.advanceTimersByTime(7900) })
  expect(srcOf()).toContain('explaining.webp')

  act(() => { vi.advanceTimersByTime(400) })
  expect(srcOf()).toContain('idle.webp') // 满 10s 一轮才回待机
})

test('没有吐字就结束（被中断 / 空回答）：直接回待机，不误播 10s 讲解', () => {
  current = render(<Harness status="thinking" />)
  act(() => { vi.advanceTimersByTime(500) })
  current.rerender(<Harness status="explaining" />)
  expect(srcOf()).toContain('idle.webp')
})

test('出错：状态跃迁时播一次，5s 后回待机', () => {
  current = render(<Harness status="idle" />)
  current.rerender(<Harness status="error" />)
  expect(srcOf()).toContain('error.webp')
  act(() => { vi.advanceTimersByTime(5200) })
  expect(srcOf()).toContain('idle.webp')
})

test('悬停：满 3s 才行礼，播完回待机', () => {
  current = render(<Harness status="idle" hovered />)
  act(() => { vi.advanceTimersByTime(2900) })
  expect(srcOf()).toContain('idle.webp')

  act(() => { vi.advanceTimersByTime(200) })
  expect(srcOf()).toContain('greet.webp')

  act(() => { vi.advanceTimersByTime(5200) })
  expect(srcOf()).toContain('idle.webp')
})

test('悬停：思考中不打断动作', () => {
  current = render(<Harness status="thinking" hovered />)
  expect(srcOf()).toContain('thinking-intro.webp')
  act(() => { vi.advanceTimersByTime(3500) })
  expect(srcOf()).toContain('thinking-loop.webp')
})

test('拖动：按下从第 1 帧拎起，播完接悬空往复，按住多久都不回待机', () => {
  current = render(<Harness status="idle" />)
  expect(srcOf()).toContain('idle.webp')

  current.rerender(<Harness status="idle" dragging />)
  expect(srcOf()).toContain('drag-intro.webp')

  // 上升段 0.83s：没播完不能提前切
  act(() => { vi.advanceTimersByTime(600) })
  expect(srcOf()).toContain('drag-intro.webp')

  act(() => { vi.advanceTimersByTime(400) })
  expect(srcOf()).toContain('drag-loop.webp')

  // 一直按着就一直悬空往复
  act(() => { vi.advanceTimersByTime(30000) })
  expect(srcOf()).toContain('drag-loop.webp')
})

test('松手：播落地收尾，播完才回待机', () => {
  current = render(<Harness status="idle" dragging />)
  act(() => { vi.advanceTimersByTime(1200) })
  expect(srcOf()).toContain('drag-loop.webp')

  current.rerender(<Harness status="idle" />)
  expect(srcOf()).toContain('drop.webp')

  // 落地有 3.08s，中途不能掐断
  act(() => { vi.advanceTimersByTime(2000) })
  expect(srcOf()).toContain('drop.webp')

  act(() => { vi.advanceTimersByTime(1200) })
  expect(srcOf()).toContain('idle.webp')
})

test('拖动中状态跃迁不打断动作，松手落地后按当时状态结算', () => {
  current = render(<Harness status="thinking" />)
  expect(srcOf()).toContain('thinking-intro.webp')

  current.rerender(<Harness status="thinking" dragging />)
  expect(srcOf()).toContain('drag-intro.webp')

  // 拖着的时候思考结束（状态粘滞到 explaining），动作不能被拽回待机
  current.rerender(<Harness status="explaining" dragging />)
  expect(srcOf()).toContain('drag-intro.webp')
  act(() => { vi.advanceTimersByTime(1000) })
  expect(srcOf()).toContain('drag-loop.webp')

  current.rerender(<Harness status="explaining" />)
  expect(srcOf()).toContain('drop.webp')
  act(() => { vi.advanceTimersByTime(3200) })
  expect(srcOf()).toContain('idle.webp')
})

test('思考中被拖动，松手落地后接回思考，而不是干站着', () => {
  current = render(<Harness status="thinking" />)
  current.rerender(<Harness status="thinking" dragging />)
  expect(srcOf()).toContain('drag-intro.webp')

  current.rerender(<Harness status="thinking" />)
  expect(srcOf()).toContain('drop.webp')

  act(() => { vi.advanceTimersByTime(3200) })
  expect(srcOf()).toContain('thinking-intro.webp')

  act(() => { vi.advanceTimersByTime(3300) })
  expect(srcOf()).toContain('thinking-loop.webp')
})
