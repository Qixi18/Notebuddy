import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { SettingsPanel } from '../src/components/SettingsPanel'
import { api } from '../src/api'
import type { SettingsStatus } from '../src/types'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

test('settings offers both routes and saves the selected default', async () => {
  const status: SettingsStatus = {
    deepseek: { configured: true, masked_key: '********', base_url: 'https://api.example.test', model: 'vision', timeout_seconds: 60 },
    embedding: { configured: false, masked_key: null, base_url: null, model: null, timeout_seconds: null },
    storage: { data_dir: 'test', database: 'test.db', max_upload_mb: 50, processing_route: 'standard' },
    limits: { allowed_extensions: ['.pdf'], editable_keys: ['NOTEBOOK_DOCUMENT_PROCESSING_ROUTE'], secret_write_enabled: false, token_required: false },
    source: { env_path: 'test.env', env_exists: true, override_keys: [] },
  }
  vi.spyOn(api, 'getSettings').mockResolvedValue(status)
  const save = vi.spyOn(api, 'updateSettings').mockResolvedValue({ updated: ['NOTEBOOK_DOCUMENT_PROCESSING_ROUTE'], backup_path: null, warnings: [], status: { ...status, storage: { ...status.storage, processing_route: 'llm' } } })
  render(<SettingsPanel onClose={() => {}} />)
  const select = await screen.findByLabelText('默认文档处理路线')
  expect(screen.getByRole('option', { name: '标准处理' })).toBeTruthy()
  expect(screen.getByRole('option', { name: '全程 AI' })).toBeTruthy()
  fireEvent.change(select, { target: { value: 'llm' } })
  fireEvent.click(screen.getByRole('button', { name: /保存/ }))
  await waitFor(() => expect(save).toHaveBeenCalledWith({ NOTEBOOK_DOCUMENT_PROCESSING_ROUTE: 'llm' }, undefined))
  expect((select as HTMLSelectElement).value).toBe('llm')
})
