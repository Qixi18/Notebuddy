import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { AssistantMessageMarkdown, AssistantMessageSource } from '../src/features/assistant/AssistantMessageContent'

afterEach(cleanup)

test('assistant message renders math and a clickable course citation', () => {
  const openSource = vi.fn()
  render(<>
    <AssistantMessageMarkdown content={'**证明**：$x^2$'} />
    <AssistantMessageSource
      source={{ source_type: 'course_material', material_id: 'm1', page_number: 2,
        lecture_title: '第一讲', location_label: '第 2 页', snippet: '公式来源' }}
      onOpen={openSource}
    />
  </>)

  expect(screen.getByText('证明').tagName).toBe('STRONG')
  expect(document.querySelector('.katex')).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /第一讲/ }))
  expect(openSource).toHaveBeenCalledOnce()
})

test('web citation opens externally with safe link attributes', () => {
  render(<AssistantMessageSource source={{ source_type: 'web', url: 'https://example.org',
    title: '参考资料', site_name: 'example.org', snippet: '节选' }} />)
  const link = screen.getByRole('link', { name: /参考资料/ })
  expect(link.getAttribute('target')).toBe('_blank')
  expect(link.getAttribute('rel')).toContain('noreferrer')
})

test('outdated citations stay identifiable and unavailable evidence cannot be opened', () => {
  const openSource = vi.fn()
  const { rerender } = render(<AssistantMessageSource source={{
    source_type: 'course_material', material_id: 'm1', page_number: 2,
    lecture_title: '第一讲', snippet: '解析版本已更新', source_status: 'stale',
  }} onOpen={openSource} />)
  expect(screen.getByText('来源已更新')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /第一讲/ }))
  expect(openSource).toHaveBeenCalledOnce()

  // 资料已删除：来源标记为不可用，卡片退化成静态展示，不能再跳转
  rerender(<AssistantMessageSource source={{
    source_type: 'course_material', material_id: 'm1', page_number: 2,
    lecture_title: '第一讲', snippet: '资料已删除', source_status: 'unavailable',
  }} onOpen={openSource} />)
  expect(screen.getByText(/来源已不可用/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: /第一讲/ })).toBeNull()
  expect(openSource).toHaveBeenCalledOnce()
})
