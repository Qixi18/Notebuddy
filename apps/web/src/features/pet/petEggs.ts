import type { PetActionId } from './petActions'

/**
 * 桌宠彩蛋：文案、动作映射、每会话只放一次的节流，以及"提问"信号的极简事件总线
 * （提问发生在 AssistantPage，彩蛋逻辑住在 PetAvatar，中间用总线解耦，避免 prop 钻透）。
 *
 * 设计约束：
 * - 每个彩蛋在同一个页面会话里只触发一次，否则连点/反复悬停会把它变成噪声；
 * - 彩蛋只借用已有动作素材（error/greet/thinking-intro），不额外增加体积；
 * - 台词一律挂人设：剧团女高音、怕"不被需要"，但不过度自贬。
 */

export type PetEggId = 'poke' | 'repeat' | 'night' | 'drafting' | 'return'

export type PetEggCommand = {
  id: PetEggId
  action: PetActionId
  bubble: string
  /** 自增序号：动作机与气泡都靠它判断"这是一条新命令" */
  nonce: number
}

/** 彩蛋借用哪个已交付的动作 */
export const PET_EGG_ACTIONS: Record<PetEggId, PetActionId> = {
  poke: 'error',        // 愣住→肩塌，正好演"被当铃铛摇"的委屈
  repeat: 'greet',      // 欠身：像在说"刚才那句，我再说一遍"
  night: 'greet',
  drafting: 'thinking-intro', // 歪头等着
  return: 'greet',
}

export const PET_EGG_BUBBLES: Record<PetEggId, string> = {
  poke: '我唱的是咏叹调，不是门铃。',
  repeat: '……上一句，我唱得不够清楚吗？',
  night: '这个点的剧场，回声最好听。',
  drafting: '我在等你的下一句 ♪',
  return: '你回来了。刚才那段，我唱到第二幕了。',
}

const fired = new Set<PetEggId>()
let nonce = 0

export function hasFired(id: PetEggId): boolean {
  return fired.has(id)
}

/** 放一个彩蛋；本会话已放过则返回 null */
export function fireEgg(id: PetEggId): PetEggCommand | null {
  if (fired.has(id)) return null
  fired.add(id)
  return { id, action: PET_EGG_ACTIONS[id], bubble: PET_EGG_BUBBLES[id], nonce: ++nonce }
}

/** 测试用：重置"已放过"记录 */
export function resetEggs(): void {
  fired.clear()
  nonce = 0
  questionListeners.clear()
}

/* ---------------- 提问信号 ---------------- */

type QuestionListener = (text: string, at: number) => void
const questionListeners = new Set<QuestionListener>()

export function reportQuestion(text: string): void {
  const trimmed = text.trim()
  if (!trimmed) return
  for (const listener of questionListeners) listener(trimmed, Date.now())
}

export function onQuestion(listener: QuestionListener): () => void {
  questionListeners.add(listener)
  return () => { questionListeners.delete(listener) }
}

/** 同一句话重问的判定窗口 */
export const PET_REPEAT_WINDOW_MS = 10 * 60 * 1000
/** 连点判定：几次以内、多长时间算"被当铃铛摇" */
export const PET_POKE_COUNT = 8
export const PET_POKE_WINDOW_MS = 3000
/** 草稿停笔多久提示 */
export const PET_DRAFT_IDLE_MS = 30_000
/** 离开多久回来才打招呼 */
export const PET_AWAY_MS = 60_000
