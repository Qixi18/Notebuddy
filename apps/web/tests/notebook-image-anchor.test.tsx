import { createRef } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { NotebookEditor, type NotebookEditorHandle } from '../src/features/notebook-editor/NotebookEditor'

afterEach(cleanup)

test('a completed image upload cannot insert at a stale document position', async () => {
  let finishUpload!: (value: { src: string; attachmentId: string }) => void
  const upload = vi.fn(() => new Promise<{ src: string; attachmentId: string }>((resolve) => { finishUpload = resolve }))
  const ref = createRef<NotebookEditorHandle>()
  render(<NotebookEditor
    ref={ref}
    initialContent={{ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '原文' }] }] }}
    onChange={() => undefined}
    onUploadImage={upload}
  />)
  await waitFor(() => expect(ref.current?.editor).toBeTruthy())
  fireEvent.change(screen.getByLabelText('上传笔记图片'), {
    target: { files: [new File(['image'], 'figure.png', { type: 'image/png' })] },
  })
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
  act(() => { ref.current?.editor?.chain().focus().insertContent('新输入').run() })
  await act(async () => {
    finishUpload({ src: '/api/v1/notebook-attachments/image-1', attachmentId: 'image-1' })
    await Promise.resolve()
  })
  expect(screen.getByRole('alert').textContent).toContain('正文发生了变化')
  expect(document.querySelector('.nb-prosemirror img')).toBeNull()
})
