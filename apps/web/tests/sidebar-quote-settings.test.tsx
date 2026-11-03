import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api } from '../src/api'
import { AppLayout, WorkspaceProvider } from '../src/components/AppLayout'
import type { SettingsStatus } from '../src/types'

vi.mock('../src/features/assistant/AssistantDock', () => ({ AssistantDock: () => null }))

const status: SettingsStatus = {
  deepseek: { configured: false, masked_key: null, base_url: 'https://api.example.test', model: 'test', timeout_seconds: 60 },
  embedding: { configured: false, masked_key: null, base_url: null, model: null, timeout_seconds: null },
  vision: { configured: false, masked_key: null, base_url: null, model: null, timeout_seconds: 60, image_capability: { status: 'unconfigured', supports_image_input: false } },
  storage: { data_dir: 'test', database: 'test.db', max_upload_mb: 50, processing_route: 'standard' },
  limits: { allowed_extensions: ['.pdf'], editable_keys: ['NOTEBOOK_DOCUMENT_PROCESSING_ROUTE'], secret_write_enabled: false, token_required: false },
  source: { env_path: 'test.env', env_exists: true, override_keys: [] },
}

const workspace = {
  courses: [], error: undefined, setError: () => {}, noteDirty: false, setEditingNote: () => {},
} as never

beforeEach(() => {
  localStorage.clear()
  vi.spyOn(api, 'getSettings').mockResolvedValue(status)
})
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })

function renderHome() {
  const router = createMemoryRouter([
    { path: '/', element: <WorkspaceProvider value={workspace}><AppLayout /></WorkspaceProvider> },
  ])
  return render(<RouterProvider router={router} />)
}

async function openQuoteEditor() {
  fireEvent.click(screen.getByRole('button', { name: '打开设置' }))
  return await screen.findByRole('textbox', { name: '侧边栏寄语' })
}

function visibleQuote() {
  return document.querySelector('.home-sidebar-quote')?.textContent
}

test('saving a multiline quote updates the sidebar and survives remount without a server settings write', async () => {
  const remoteSave = vi.spyOn(api, 'updateSettings')
  const view = renderHome()
  const field = await openQuoteEditor()
  fireEvent.change(field, { target: { value: '慢慢积累，\n每天进步一点。' } })
  expect(visibleQuote()).not.toContain('慢慢积累')
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await waitFor(() => expect(visibleQuote()).toBe('慢慢积累，\n每天进步一点。'))
  expect(remoteSave).not.toHaveBeenCalled()

  view.unmount()
  renderHome()
  expect(visibleQuote()).toBe('慢慢积累，\n每天进步一点。')
  expect((await openQuoteEditor() as HTMLTextAreaElement).value).toBe('慢慢积累，\n每天进步一点。')
})

test('cancel discards quote edits and an empty saved quote restores the default', async () => {
  renderHome()
  let field = await openQuoteEditor()
  const initial = (field as HTMLTextAreaElement).value
  fireEvent.change(field, { target: { value: '未保存的修改' } })
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  field = await openQuoteEditor()
  expect((field as HTMLTextAreaElement).value).toBe(initial)
  fireEvent.change(field, { target: { value: '自定义的寄语' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await waitFor(() => expect(visibleQuote()).toBe('自定义的寄语'))
  fireEvent.change(field, { target: { value: '   \n  ' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await waitFor(() => expect(visibleQuote()).toBe(initial))
})

test('the quote remains editable when server settings are unavailable', async () => {
  vi.mocked(api.getSettings).mockRejectedValue(new Error('设置服务暂不可用'))
  renderHome()
  const field = await openQuoteEditor()
  await screen.findByRole('alert')
  fireEvent.change(field, { target: { value: '按自己的节奏学习。' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await waitFor(() => expect(visibleQuote()).toBe('按自己的节奏学习。'))
})

test('a failed combined save keeps the original quote until the settings save succeeds', async () => {
  const remoteSave = vi.spyOn(api, 'updateSettings').mockRejectedValueOnce(new Error('保存失败'))
    .mockResolvedValue({ updated: ['NOTEBOOK_DOCUMENT_PROCESSING_ROUTE'], backup_path: null, warnings: [], status: { ...status, storage: { ...status.storage, processing_route: 'llm' } } })
  renderHome()
  const field = await openQuoteEditor()
  const initial = visibleQuote()
  fireEvent.change(field, { target: { value: '新的寄语' } })
  fireEvent.change(await screen.findByLabelText('默认文档处理路线'), { target: { value: 'llm' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await screen.findByText('保存失败')
  expect(visibleQuote()).toBe(initial)
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await waitFor(() => expect(visibleQuote()).toBe('新的寄语'))
  expect(remoteSave).toHaveBeenLastCalledWith({ NOTEBOOK_DOCUMENT_PROCESSING_ROUTE: 'llm' }, undefined)
})
