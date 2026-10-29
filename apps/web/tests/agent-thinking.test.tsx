import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { AgentThinking } from '../src/features/assistant/AgentThinking'

afterEach(cleanup)

describe('AgentThinking', () => {
  test('live 时只显示「思考中」，不渲染任何思维链正文', () => {
    const { container } = render(<AgentThinking live />)
    expect(screen.getByText('思考中')).toBeTruthy()
    expect(container.querySelector('pre')).toBeNull()
    expect(container.textContent).toBe('思考中')
  })

  test('非 live 时不渲染任何内容', () => {
    const { container } = render(<AgentThinking live={false} />)
    expect(container.textContent).toBe('')
  })
})
