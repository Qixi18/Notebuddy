import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { ApiError, api } from '../../api'
import type { Note } from '../../types'

export function useNoteEditor(
  selectedNote: Note | undefined,
  setNotes: Dispatch<SetStateAction<Note[]>>,
  setError: Dispatch<SetStateAction<string | undefined>>,
) {
  const [noteDraft, writeDraft] = useState('')
  const [editingNote, setEditingNote] = useState(false)
  const [noteSaving, setNoteSaving] = useState(false)
  const draftNoteId = useRef<string | undefined>(undefined)
  const currentNote = useRef(selectedNote)
  currentNote.current = selectedNote
  const draft = useRef({ value: '', generation: 0 })
  const saveSequence = useRef(0)
  const setNoteDraft = useCallback<Dispatch<SetStateAction<string>>>((value) => {
    const next = typeof value === 'function' ? value(draft.current.value) : value
    draft.current = { value: next, generation: draft.current.generation + 1 }
    writeDraft(next)
  }, [])
  const noteDirty = Boolean(editingNote && selectedNote && noteDraft !== selectedNote.content_markdown)

  useEffect(() => {
    if (draftNoteId.current !== selectedNote?.id) {
      draftNoteId.current = selectedNote?.id
      setNoteDraft(selectedNote?.content_markdown ?? '')
      setEditingNote(false)
      setNoteSaving(false)
    } else if (!editingNote) {
      setNoteDraft(selectedNote?.content_markdown ?? '')
    }
  }, [selectedNote?.id, selectedNote?.content_markdown, editingNote])

  async function saveNote() {
    if (!selectedNote) return
    const noteId = selectedNote.id
    const generation = draft.current.generation
    const sequence = ++saveSequence.current
    try {
      setNoteSaving(true)
      const updated = await api.updateNote(selectedNote.id, noteDraft, selectedNote.revision_number)
      setNotes((current) => current.map((note) => note.id === updated.id && note.revision_number <= updated.revision_number ? updated : note))
      if (currentNote.current?.id === noteId && draft.current.generation === generation
        && currentNote.current.revision_number <= updated.revision_number) {
        setNoteDraft(updated.content_markdown)
        setEditingNote(false)
        setError(undefined)
      }
    } catch (cause) {
      if (currentNote.current?.id === noteId) setError(cause instanceof ApiError && cause.status === 409
        ? '这条笔记已在其他操作中更新。你的修改仍保留在编辑框里，请先复制保存，再刷新页面载入最新版本并手动合并。'
        : cause instanceof Error ? cause.message : '笔记保存失败')
    } finally {
      if (currentNote.current?.id === noteId && saveSequence.current === sequence) setNoteSaving(false)
    }
  }

  async function reloadNote() {
    if (!selectedNote) return
    const noteId = selectedNote.id
    const generation = draft.current.generation
    const latest = await api.getNote(selectedNote.id)
    setNotes((current) => current.map((note) => note.id === latest.id && note.revision_number <= latest.revision_number ? latest : note))
    if (currentNote.current?.id === noteId && draft.current.generation === generation
      && currentNote.current.revision_number <= latest.revision_number) {
      setNoteDraft(latest.content_markdown)
      setEditingNote(true)
      setError(undefined)
    }
  }

  return {
    noteDraft, setNoteDraft, editingNote, setEditingNote,
    noteSaving, noteDirty, saveNote, reloadNote,
  }
}
