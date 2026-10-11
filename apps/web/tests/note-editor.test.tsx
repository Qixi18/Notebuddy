import { useState } from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { useNoteEditor } from '../src/features/notes/useNoteEditor'
import type { Note } from '../src/types'

vi.mock('../src/api', () => ({
  api: { updateNote: vi.fn(), getNote: vi.fn() },
  ApiError: class extends Error { status = 409 },
}))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const first = { id: 'n1', content_markdown: 'first', revision_number: 1 } as Note
const second = { id: 'n2', content_markdown: 'second', revision_number: 1 } as Note
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
function editor() {
  return renderHook(({ noteId }) => {
    const [notes, setNotes] = useState([first, second])
    const [error, setError] = useState<string>()
    return { ...useNoteEditor(notes.find((n) => n.id === noteId), setNotes, setError), notes, error }
  }, { initialProps: { noteId: first.id } })
}

test('late save updates its note without replacing another section draft', async () => {
  const request = deferred<Note>()
  vi.mocked(api.updateNote).mockReturnValue(request.promise)
  const { result, rerender } = editor()
  act(() => { result.current.setEditingNote(true); result.current.setNoteDraft('submitted first') })
  let saving!: Promise<void>
  act(() => { saving = result.current.saveNote() })
  rerender({ noteId: second.id })
  act(() => { result.current.setEditingNote(true); result.current.setNoteDraft('second draft') })
  await act(async () => { request.resolve({ ...first, content_markdown: 'submitted first', revision_number: 2 }); await saving })
  expect(result.current.noteDraft).toBe('second draft')
  expect(result.current.editingNote).toBe(true)
  expect(result.current.notes.find((n) => n.id === first.id)?.revision_number).toBe(2)
})

test('typing during save retains the newer unsaved text', async () => {
  const request = deferred<Note>()
  vi.mocked(api.updateNote).mockReturnValue(request.promise)
  const { result } = editor()
  act(() => { result.current.setEditingNote(true); result.current.setNoteDraft('submitted') })
  let saving!: Promise<void>
  act(() => { saving = result.current.saveNote() })
  act(() => result.current.setNoteDraft('typed while saving'))
  await act(async () => { request.resolve({ ...first, content_markdown: 'submitted', revision_number: 2 }); await saving })
  expect(result.current.noteDraft).toBe('typed while saving')
  expect(result.current.editingNote).toBe(true)
  expect(result.current.noteDirty).toBe(true)
})

test('late reload cannot put another note into the current editor', async () => {
  const request = deferred<Note>()
  vi.mocked(api.getNote).mockReturnValue(request.promise)
  const { result, rerender } = editor()
  let loading!: Promise<void>
  act(() => { loading = result.current.reloadNote() })
  rerender({ noteId: second.id })
  act(() => { result.current.setEditingNote(true); result.current.setNoteDraft('keep second') })
  await act(async () => { request.resolve({ ...first, content_markdown: 'latest first', revision_number: 2 }); await loading })
  expect(result.current.noteDraft).toBe('keep second')
  expect(result.current.editingNote).toBe(true)
})
