import type { Course } from '../../types'
import type { KnowledgeTreeView } from './sceneTypes'

export function selectHomeCourses(courses: Course[]): Course[] {
  return [...courses].sort((a, b) => (b.last_opened_at ?? b.created_at).localeCompare(a.last_opened_at ?? a.created_at) || a.id.localeCompare(b.id)).slice(0, 3)
}
type SceneSnapshot = { view?: KnowledgeTreeView; courseIds: string[] }
export function readSceneSnapshot(key: string): SceneSnapshot | undefined {
  try {
    const value = JSON.parse(sessionStorage.getItem(`notebuddy.scene.${key}`) ?? 'null') as SceneSnapshot | null
    if (!value || !Array.isArray(value.courseIds) || !value.courseIds.every(id => typeof id === 'string')) return undefined
    const v = value.view
    if (v && (!Number.isFinite(v.camera?.x) || !Number.isFinite(v.camera?.y) || !(v.camera?.k > 0) || !(v.viewport?.width > 0) || !(v.viewport?.height > 0) || !v.slots)) return { courseIds: value.courseIds }
    return value
  } catch { return undefined }
}
export function saveSceneSnapshot(key: string, value: SceneSnapshot) {
  try { sessionStorage.setItem(`notebuddy.scene.${key}`, JSON.stringify(value)) } catch { /* Scene remains usable without storage. */ }
}
