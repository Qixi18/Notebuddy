import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { AgentThinking } from '../src/features/assistant/AgentThinking'

afterEach(cleanup)

describe('AgentThinking', () => {
  test('思考中显示「思考中」并实时渲染思维链正文', () => {
    const { container } = render(<AgentThinking thinking="先看行列式的定义" live />)
    expect(screen.getByText('思考中')).toBeTruthy()
    expect(container.querySelector('pre')?.textContent).toBe('先看行列式的定义')
  })

  test('思考中只渲染尾部 600 字，避免长思维链把容器顶飞', () => {
    const long = `${'开头'.repeat(400)}末尾标记`
    const { container } = render(<AgentThinking thinking={long} live />)
    const body = container.querySelector('pre')?.textContent ?? ''
    expect(body.startsWith('…')).toBe(true)
    expect(body.endsWith('末尾标记')).toBe(true)
    expect(body.length).toBeLessThan(long.length)
  })

  test('没有思维链文本时整体不渲染（连转圈也不留）', () => {
    const { container } = render(<AgentThinking thinking="" live />)
    expect(container.textContent).toBe('')
  })

  test('答完后折叠成「已深度思考」，默认不展开正文', () => {
    const { container } = render(<AgentThinking thinking="完整思维链" live={false} />)
    expect(screen.getByText(/已深度思考（点击展开）/)).toBeTruthy()
    expect(container.querySelector('pre')).toBeNull()
  })

  test('点「已深度思考」展开全文，再点收起', () => {
    const { container } = render(<AgentThinking thinking="完整思维链" live={false} />)
    const toggle = screen.getByRole('button', { name: /已深度思考/ })

    fireEvent.click(toggle)
    expect(container.querySelector('pre')?.textContent).toBe('完整思维链')
    expect(screen.getByText(/已深度思考（点击收起）/)).toBeTruthy()

    fireEvent.click(toggle)
    expect(container.querySelector('pre')).toBeNull()
  })
})
