import { useCallback, useEffect, useRef, useState } from 'react'

import {
  PET_AWAY_MS,
  PET_DRAFT_IDLE_MS,
  PET_POKE_COUNT,
  PET_POKE_WINDOW_MS,
  PET_REPEAT_WINDOW_MS,
  fireEgg,
  onQuestion,
  type PetEggCommand,
} from './petEggs'

/**
 * 五个"零新增素材"的彩蛋触发器：
 *
 *   连点 8 下（3s 内）      → poke     被当铃铛摇
 *   10 分钟内重问同一句     → repeat   上一句没唱清楚？
 *   00:00–05:00 打开答疑页  → night    夜场回声
 *   草稿停笔 30s            → drafting 在等你的下一句
 *   离开 ≥60s 再回来        → return   你回来了
 *
 * 忙（思考/输出）期间触发的彩蛋先挂起，等这一轮结束再放，避免打断动作又立刻被覆盖。
 */
const NIGHT_FROM = 0
const NIGHT_TO = 5

export function usePetEasterEggs({ busy, draft }: { busy: boolean; draft: string }): {
  command: PetEggCommand | null
  noteClick: () => void
} {
  const [command, setCommand] = useState<PetEggCommand | null>(null)
  const pendingRef = useRef<PetEggCommand | null>(null)
  const busyRef = useRef(busy)
  busyRef.current = busy

  const deliver = useCallback((next: PetEggCommand | null) => {
    if (!next) return
    if (busyRef.current) {
      pendingRef.current = next
      return
    }
    setCommand(next)
  }, [])

  /* 这一轮问答结束后，把挂起的彩蛋放出来 */
  useEffect(() => {
    if (busy) return
    const pending = pendingRef.current
    if (!pending) return
    pendingRef.current = null
    setCommand(pending)
  }, [busy])

  /* 连点 */
  const clicksRef = useRef<number[]>([])
  const noteClick = useCallback(() => {
    const now = Date.now()
    clicksRef.current = [...clicksRef.current.filter((at) => now - at < PET_POKE_WINDOW_MS), now]
    if (clicksRef.current.length < PET_POKE_COUNT) return
    clicksRef.current = []
    deliver(fireEgg('poke'))
  }, [deliver])

  /* 同一句话重问 */
  const lastQuestionRef = useRef<{ text: string; at: number } | null>(null)
  useEffect(() => onQuestion((text, at) => {
    const previous = lastQuestionRef.current
    lastQuestionRef.current = { text, at }
    if (!previous || previous.text !== text) return
    if (at - previous.at > PET_REPEAT_WINDOW_MS) return
    deliver(fireEgg('repeat'))
  }), [deliver])

  /* 夜场：打开页面时若在凌晨 */
  useEffect(() => {
    const hour = new Date().getHours()
    if (hour < NIGHT_FROM || hour >= NIGHT_TO) return
    const timer = window.setTimeout(() => deliver(fireEgg('night')), 2500)
    return () => window.clearTimeout(timer)
  }, [deliver])

  /* 草稿停笔：草稿一变就重新计时，空草稿不触发 */
  useEffect(() => {
    if (busy || !draft.trim()) return
    const timer = window.setTimeout(() => deliver(fireEgg('drafting')), PET_DRAFT_IDLE_MS)
    return () => window.clearTimeout(timer)
  }, [draft, busy, deliver])

  /* 离开再回来：用时间戳判定，后台标签页的定时器节流也不会误判 */
  useEffect(() => {
    let leftAt = 0
    const markAway = () => { if (!leftAt) leftAt = Date.now() }
    const maybeReturn = () => {
      if (!leftAt) return
      const away = Date.now() - leftAt
      leftAt = 0
      if (away >= PET_AWAY_MS) deliver(fireEgg('return'))
    }
    const onVisibility = () => { document.hidden ? markAway() : maybeReturn() }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('blur', markAway)
    window.addEventListener('focus', maybeReturn)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('blur', markAway)
      window.removeEventListener('focus', maybeReturn)
    }
  }, [deliver])

  return { command, noteClick }
}
