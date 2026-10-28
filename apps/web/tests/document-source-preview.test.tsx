import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { api } from '../src/api'
import { DocumentSourcePreview } from '../src/features/notebook-editor/DocumentSourcePreview'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

test('loads scoped parse version, page evidence and coverage in the Notebook preview', async () => {
  vi.spyOn(api, 'listAssetParseRuns').mockResolvedValue([{
    id: 'run-1', asset_id: 'asset-1', status: 'completed', is_current: true,
    page_count: 2, text_chars: 40, quality_status: 'complete', quality: { status: 'complete', warnings: [] },
    created_at: '2026-10-27T00:00:00Z',
  }])
  vi.spyOn(api, 'getAssetDocument').mockResolvedValue({
    run: {
      id: 'run-1', asset_id: 'asset-1', status: 'completed', is_current: true,
      page_count: 2, text_chars: 40, quality_status: 'complete', quality: { status: 'complete', warnings: [] },
      created_at: '2026-10-27T00:00:00Z',
    },
    pages: [1, 2].map((page_number) => ({
      page_number, status: 'parsed', extraction: 'native_text', confidence: 0.95,
      warnings: [], text_chars: 20, render_url: null,
    })),
    sections: [],
  })
  vi.spyOn(api, 'getAssetCoverage').mockResolvedValue({
    asset_id: 'asset-1', asset_name: 'limits.pdf', parse_run_id: 'run-1', total_blocks: 1, cited_blocks: 1,
    pages: [{ page_number: 1, total: 1, cited: 0 }, { page_number: 2, total: 1, cited: 1 }],
    blocks: [{ block_id: 'b-2', page_number: 2, quote: '极限证据', citations: [{
      notebook_id: 'book-1', notebook_title: '极限笔记', block_id: 'h-2', page_number: 2,
    }] }],
  })
  const evidence = vi.spyOn(api, 'getAssetPageEvidence').mockResolvedValue([{
    block_id: 'b-2', page_number: 2, type: 'paragraph', level: 0, text: '极限证据',
    latex: null, confidence: 0.95, extraction: 'native_text', warnings: [],
  }])
  vi.spyOn(api, 'listPages').mockResolvedValue([])
  vi.spyOn(api, 'listMaterialWebSources').mockResolvedValue([])

  render(<DocumentSourcePreview assetId="asset-1" notebookId="book-1" materialId="material-1"
    initialPage={2} fileName="limits.pdf" mimeType="application/pdf" onClose={() => undefined} />)

  expect(await screen.findByText('极限证据')).toBeTruthy()
  expect(screen.getByText(/解析质量：complete/)).toBeTruthy()
  expect(screen.getByText(/关联 Notebook：极限笔记/)).toBeTruthy()
  expect(screen.getByText('来源覆盖 · 1/1 个解析块已关联')).toBeTruthy()
  expect(api.listAssetParseRuns).toHaveBeenCalledWith('asset-1', 'book-1')
  await waitFor(() => expect(evidence).toHaveBeenCalledWith('asset-1', 'book-1', 2, 'run-1'))

  fireEvent.click(screen.getByRole('button', { name: '第 1 页 · 0/1' }))
  await waitFor(() => expect(evidence).toHaveBeenCalledWith('asset-1', 'book-1', 1, 'run-1'))
  fireEvent.click(screen.getByRole('button', { name: '第 1 页 · 95%' }))
  await waitFor(() => expect(evidence).toHaveBeenCalledWith('asset-1', 'book-1', 1, 'run-1'))
})

test('shows partial parse warnings and generation limits to the user', async () => {
  const run = {
    id: 'run-partial', asset_id: 'asset-1', status: 'completed', is_current: true,
    page_count: 2, text_chars: 24, quality_status: 'partial',
    quality: {
      status: 'partial', generation_allowed: true,
      issues: [{ code: 'empty_pages', severity: 'warning', message: '第 2 页没有可用文字或结构' }],
    },
    created_at: '2026-10-27T00:00:00Z',
  }
  vi.spyOn(api, 'listAssetParseRuns').mockResolvedValue([run])
  vi.spyOn(api, 'getAssetDocument').mockResolvedValue({
    run,
    pages: [
      { page_number: 1, status: 'parsed', extraction: 'native_text', confidence: 0.95, warnings: [], text_chars: 24, render_url: null },
      { page_number: 2, status: 'empty', extraction: 'none', confidence: null, warnings: ['本页没有可用的文字或结构化内容'], text_chars: 0, render_url: null },
    ],
    sections: [],
  })
  vi.spyOn(api, 'getAssetCoverage').mockResolvedValue({
    asset_id: 'asset-1', asset_name: 'limits.pdf', parse_run_id: run.id, total_blocks: 0, cited_blocks: 0,
    pages: [], blocks: [],
  })
  vi.spyOn(api, 'getAssetPageEvidence').mockResolvedValue([])
  vi.spyOn(api, 'listPages').mockResolvedValue([])
  vi.spyOn(api, 'listMaterialWebSources').mockResolvedValue([])

  render(<DocumentSourcePreview assetId="asset-1" notebookId="book-1" materialId="material-1"
    fileName="limits.pdf" mimeType="application/pdf" onClose={() => undefined} />)

  expect(await screen.findByText(/生成内容仅依据已识别页面/)).toBeTruthy()
  expect(screen.getByText('第 2 页没有可用文字或结构')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '第 2 页' }))
  expect(await screen.findByText('本页没有可用的文字或结构化内容')).toBeTruthy()
})
