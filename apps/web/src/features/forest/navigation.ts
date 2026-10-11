import type { Camera } from './types'
type Section = { id: string; material_id: string | null }
export type ForestViewState = {
  camera: Camera
  viewport?: { width: number; height: number }
  focus?: string
  expanded: string[]
}
export const FOREST_VIEW_KEY = 'notebuddy.forest.view.v1'
export const FOREST_SLOTS_KEY = 'notebuddy.forest.slots.v1'
export function forestNotePath(courseId: string, section: Section): string {
  const query = new URLSearchParams({
    chapter: section.material_id ?? 'history',
    section: section.id,
  })
  return `/courses/${courseId}/notebook?${query}`
}
export function restoreForestState(raw: string | null): ForestViewState | undefined {
  try {
    const data = JSON.parse(raw ?? 'null') as ForestViewState | null
    if (
      !data ||
      ![data.camera?.x, data.camera?.y, data.camera?.k].every(Number.isFinite) ||
      data.camera.k < 0.35 ||
      data.camera.k > 2.5 ||
      !Array.isArray(data.expanded) ||
      !data.expanded.every((id) => typeof id === 'string')
    )
      return undefined
    return {
      camera: data.camera,
      focus: typeof data.focus === 'string' ? data.focus : undefined,
      expanded: data.expanded,
      ...(data.viewport &&
      [data.viewport.width, data.viewport.height].every(
        (value) => Number.isFinite(value) && value > 0,
      )
        ? { viewport: data.viewport }
        : {}),
    }
  } catch {
    return undefined
  }
}
