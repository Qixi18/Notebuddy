// Below this level the scene is a course overview. Detail targets are disabled
// rather than inflated into overlapping transparent regions across whole trees.
export const DETAIL_ZOOM = .5
export const detailInteraction = (zoom: number) => zoom >= DETAIL_ZOOM
export const operationSize = (zoom: number) => 44 / Math.min(1, zoom)
