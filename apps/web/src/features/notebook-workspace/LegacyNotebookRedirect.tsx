import { useEffect, useState } from 'react'
import { Navigate, useLocation, useParams } from 'react-router-dom'

import { api } from '../../api'

export function LegacyNotebookRedirect() {
  const { courseId } = useParams<{ courseId: string }>()
  const location = useLocation()
  const requestedNotebook = new URLSearchParams(location.search).get('notebook')
  const [target, setTarget] = useState<string>()

  useEffect(() => {
    if (!courseId) {
      setTarget('/courses')
      return
    }
    let active = true
    void api.listNotebooks(courseId).then((notebooks) => {
      if (!active) return
      const inCourse = notebooks.filter((item) => item.course_id === courseId)
      const notebook = requestedNotebook
        ? inCourse.find((item) => item.id === requestedNotebook)
        : inCourse.find((item) => item.is_default) ?? inCourse[0]
      const params = new URLSearchParams(location.search)
      params.delete('notebook')
      const query = params.size ? `?${params.toString()}` : ''
      setTarget(notebook
        ? `/courses/${courseId}/notebooks/${notebook.id}${query}`
        : `/courses/${courseId}`)
    }).catch(() => {
      if (active) setTarget(`/courses/${courseId}`)
    })
    return () => { active = false }
  }, [courseId, location.search, requestedNotebook])

  return target
    ? <Navigate to={target} replace />
    : <p role="status">正在打开笔记本…</p>
}
