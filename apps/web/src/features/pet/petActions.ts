/**
 * 桌宠动作资产：id 与 public/assets/pet/<id>.webp 一一对应，
 * 由 scripts/build_pet_actions.py 从 matte-studio 的透明帧生成。
 *
 * 思考动作拆成两段，因为思考时长不确定：
 *   thinking-intro  0→75 帧正放一次
 *   thinking-loop   75↔22 帧之间往复，直到答案出来
 * 其余一次性动作播完自动回 idle。
 */
export type PetActionId = 'idle' | 'thinking-intro' | 'thinking-loop' | 'explaining' | 'explaining-loop' | 'error' | 'greet'

/** 兜底时长（秒）：与 manifest.json 的 duration 一致；拉不到 manifest 时用它 */
export const PET_ACTION_FALLBACK_SECONDS: Record<PetActionId, number> = {
  idle: 5.83,
  'thinking-intro': 3.17,
  'thinking-loop': 4.33,
  explaining: 10,
  'explaining-loop': 2,
  error: 5,
  greet: 5,
}

/** 悬停多久触发一次「行礼」 */
export const PET_HOVER_GREET_DELAY = 3000

export function petActionSrc(id: PetActionId): string {
  return `/assets/pet/${id}.webp`
}
