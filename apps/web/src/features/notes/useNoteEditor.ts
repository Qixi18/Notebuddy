import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'

import type { Note } from '../../types'

/**
 * Legacy Note editor is retired. Its state shape is kept only so old widgets
 * compile; saving is rejected and points the user at the Notebook editor.
 */
export function useNoteEditor(
  selectedNote: Note | undefined,
  _setNotes: Dispatch<SetStateAction<Note[]>>,
  setError: Dispatch<SetStateAction<string | undefined>>,
) {
  const [noteDraft, setNoteDraft] = useState(selectedNote?.content_markdown ?? '')
  const [editingNote, setEditingNote] = useState(false)

  useEffect(() => {
    setNoteDraft(selectedNote?.content_markdown ?? '')
    setEditingNote(false)
  }, [selectedNote?.id, selectedNote?.content_markdown])

  async function saveNote() {
    setError('旧 Note 正文写入已退役：请在 Notebook 编辑器中保存正文')
  }

  async function reloadNote() {
    setError('旧 Note 正文已迁移到 Notebook，请打开对应笔记查看')
  }

  return {
    noteDraft, setNoteDraft, editingNote, setEditingNote,
    noteSaving: false, noteDirty: false, saveNote, reloadNote,
  }
}
