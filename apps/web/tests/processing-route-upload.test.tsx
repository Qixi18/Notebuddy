import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { SourceUploadPanel } from '../src/features/notebook-workspace/SourceUploadPanel'

vi.mock('../src/api', () => ({ api: {
  getCapabilities: vi.fn().mockResolvedValue({ default_processing_route: 'llm', processing_routes: { llm: { max_upload_bytes: 209715200, max_pages: 2000 }, standard: { max_upload_bytes: 52428800, max_pages: 500 } } }),
  uploadNotebookAsset: vi.fn().mockResolvedValue({}),
  closeNotebookUploadBatch: vi.fn().mockResolvedValue({ id: 'b', status: 'completed', inputs: [] }),
  listNotebookGenerationJobs: vi.fn().mockResolvedValue([]), getNotebookUploadBatch: vi.fn(),
} }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

test('source upload uses the configured AI route and permits explicit standard selection', async () => {
  const { container } = render(<SourceUploadPanel notebookId="book" onDocumentUpdated={() => {}} />)
  const select = await screen.findByLabelText('本次文档处理路线')
  await waitFor(() => expect((select as HTMLSelectElement).value).toBe('llm'))
  const file = new File(['pdf'], 'source.pdf', { type: 'application/pdf' })
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
  await waitFor(() => expect(api.uploadNotebookAsset).toHaveBeenCalledWith('book', file, expect.any(String), 'llm'))
  fireEvent.change(select, { target: { value: 'standard' } })
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
  await waitFor(() => expect(api.uploadNotebookAsset).toHaveBeenLastCalledWith('book', file, expect.any(String), 'standard'))
})
