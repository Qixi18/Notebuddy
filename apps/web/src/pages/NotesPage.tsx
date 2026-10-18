import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { notebookPath } from '../features/notebook/navigation'

export function NotesPage() {
  const { courseId = '', noteId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [message, setMessage] = useState('正在定位原笔记…')
  useEffect(() => {
    let active = true
    if (!noteId) return
    void api.getNote(noteId).then((note) => {
      if (!active) return
      if (note.course_id !== courseId) { setMessage('这条笔记属于其他课程。'); return }
      if (!note.notebook_id) { setMessage('这条笔记尚无有效笔记本归属。'); return }
      navigate(notebookPath(courseId, note), { replace: true, state: location.state })
    }).catch((cause: unknown) => { if (active) setMessage(cause instanceof Error ? cause.message : '笔记读取失败') })
    return () => { active = false }
  }, [courseId, noteId, navigate])
  return <p role="status">{message}</p>
}
