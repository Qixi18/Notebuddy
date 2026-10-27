import { describe, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach } from 'vitest'

import { ContrastCards, OutlineCards } from '../src/features/assistant/AgentCards'
import type { AgentSuggestion } from '../src/api/agentStream'

afterEach(() => {
  cleanup()
  localStorage.clear()
})

const outline: Extract<AgentSuggestion, { type: 'review_outline' }> = {
  type: 'review_outline',
  id: 'o1',
  title: '需求复习提纲',
  module_count: 2,
  item_count: 3,
  modules: [
    { title: '模块设计', priority: 'high', items: [{ point: '高内聚低耦合', ref: '第 1 页' }, { point: '划分原则' }] },
    { title: '验证', priority: 'low', items: [{ point: '评审流程' }] },
  ],
}

const contrast: Extract<AgentSuggestion, { type: 'concept_contrast' }> = {
  type: 'concept_contrast',
  id: 'c1',
  pair_count: 1,
  pairs: [{
    a: '内聚', b: '耦合',
    core: '内聚看模块内部，耦合看模块之间',
    dimensions: [
      { name: '对象', a: '模块内部', b: '模块之间' },
      { name: '目标', a: '越高越好', b: '越低越好' },
    ],
    anchor: '高内聚低耦合',
  }],
}

describe('OutlineCards', () => {
  test('渲染模块清单与进度，勾选推进进度条并写入 localStorage', () => {
    render(<OutlineCards outlines={[outline]} />)
    expect(screen.getByText('需求复习提纲')).toBeTruthy()
    expect(screen.getByText('高内聚低耦合')).toBeTruthy()
    expect(screen.getByText('0/3')).toBeTruthy()
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    fireEvent.click(boxes[0])
    expect((boxes[0] as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText('1/3')).toBeTruthy()
    const stored = JSON.parse(localStorage.getItem('nb-outline-checks') ?? '{}') as Record<string, boolean>
    expect(stored['o1-0-0']).toBe(true)
  })

  test('「问这个」把要点灌回追问回调', () => {
    const onAsk = vi.fn()
    render(<OutlineCards outlines={[outline]} onAsk={onAsk} />)
    fireEvent.click(screen.getAllByText('问这个')[0])
    expect(onAsk).toHaveBeenCalledTimes(1)
    expect(String(onAsk.mock.calls[0][0])).toContain('高内聚低耦合')
  })
})

describe('ContrastCards', () => {
  test('渲染对比表与记忆锚点', () => {
    render(<ContrastCards contrasts={[contrast]} />)
    expect(screen.getByText('内聚看模块内部，耦合看模块之间')).toBeTruthy()
    expect(screen.getByText('🧠 高内聚低耦合')).toBeTruthy()
    expect(screen.getByText('越高越好')).toBeTruthy()
  })

  test('「就这对考考我」带着概念对触发追问', () => {
    const onAsk = vi.fn()
    render(<ContrastCards contrasts={[contrast]} onAsk={onAsk} />)
    fireEvent.click(screen.getByText('就这对考考我'))
    expect(onAsk).toHaveBeenCalledTimes(1)
    expect(String(onAsk.mock.calls[0][0])).toContain('内聚')
    expect(String(onAsk.mock.calls[0][0])).toContain('耦合')
  })
})
