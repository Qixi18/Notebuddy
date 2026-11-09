// Includes the last leaf's afterglow; the same deadline owns paint and receipts.
export const TREE_GROWTH_LIFETIME_MS = 6000
export const HOME_TREE_GROWTH_TIME_SCALE = 1.4
export const TREE_GROWTH_EASING = 'cubic-bezier(.4,0,.2,1)'
export const VINE_GROWTH_TRAVEL_MS = 2400
export const VINE_GROWTH_EASING = 'linear'
export type GrowthTiming = { delay: number; duration: number; easing?: string }
