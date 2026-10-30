import { useCallback, useEffect, useRef, useState } from 'react'

import type { TeacherStatus } from '../../components/TeacherCharacter'
import type { PetEggCommand } from './petEggs'
import { PET_ACTION_FALLBACK_SECONDS, PET_HOVER_GREET_DELAY, petActionSrc, type PetActionId } from './petActions'

/**
 * 桌宠动作状态机。
 *
 *   status=thinking，尚未吐字     → thinking-intro 播一次，接 thinking-loop 往复
 *   正文开始流式输出              → 立刻切讲解（不等整段答案生成完）
 *   讲解正片(10s)播完还在吐字     → 接 explaining-loop 小往复，直到输出结束
 *   输出结束 / thinking 结束      → 把当前这一轮讲解播完再回待机
 *   失败                         → 出错播一次，回待机
 *   悬停 ≥3s 且当前在待机         → 行礼播一次，回待机
 *
 * 一次性动作不靠 webp 自己循环，而是按 manifest 里的时长定时切回待机；
 * 状态本身是「粘滞」的（问过一次就一直是 explaining），所以只认状态跃迁。
 */

type Durations = Record<string, number>

const MANIFEST_URL = '/assets/pet/manifest.json'

/** 时长以 manifest 为准（素材重建后不用改代码），失败时退回内置常量 */
function useActionDurations(): Durations {
  const [durations, setDurations] = useState<Durations>(PET_ACTION_FALLBACK_SECONDS)
  useEffect(() => {
    if (typeof fetch !== 'function') return
    let cancelled = false
    fetch(MANIFEST_URL)
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { actions?: Record<string, { duration?: number }> } | null) => {
        if (cancelled || !data?.actions) return
        const next: Durations = { ...PET_ACTION_FALLBACK_SECONDS }
        for (const [id, item] of Object.entries(data.actions)) {
          if (typeof item?.duration === 'number' && item.duration > 0) next[id] = item.duration
        }
        setDurations(next)
      })
      .catch(() => { /* 读不到就用兜底时长，不影响播放 */ })
    return () => { cancelled = true }
  }, [])
  return durations
}

export function usePetAction(
  status: TeacherStatus,
  hovered: boolean,
  /** 正文正在流式输出：回答已经开写，但还没结束 */
  streaming = false,
  /** 彩蛋命令：插播一次指定动作（每会话各彩蛋只来一次，nonce 递增） */
  command: PetEggCommand | null = null,
): { action: PetActionId; src: string } {
  const durations = useActionDurations()
  const [action, setAction] = useState<PetActionId>('idle')
  const actionRef = useRef<PetActionId>('idle')
  const timerRef = useRef(0)
  /* null = 还没跑过：首帧只在「正在思考」时接上动作，不重放上一次的出错/讲解 */
  const prevStatusRef = useRef<TeacherStatus | null>(null)
  const streamingRef = useRef(streaming)
  streamingRef.current = streaming
  /** 当前讲解这一轮从哪一刻起算、总长多少：结束时至少把这一轮播完 */
  const cycleStartRef = useRef(0)
  const cycleMsRef = useRef(0)

  const apply = useCallback((next: PetActionId) => {
    actionRef.current = next
    setAction(next)
  }, [])

  const clearTimer = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = 0
  }, [])

  const secondsOf = useCallback(
    (id: PetActionId) => (durations[id] ?? PET_ACTION_FALLBACK_SECONDS[id]) * 1000,
    [durations],
  )

  /** 一次性动作：播完（按素材时长）回待机 */
  const playOnce = useCallback((next: PetActionId) => {
    clearTimer()
    apply(next)
    timerRef.current = window.setTimeout(() => apply('idle'), secondsOf(next) + 120)
  }, [apply, clearTimer, secondsOf])

  /** 思考：先正放一次，再切到 75↔22 的往复段 */
  const playThinking = useCallback(() => {
    clearTimer()
    apply('thinking-intro')
    timerRef.current = window.setTimeout(() => {
      if (actionRef.current === 'thinking-intro') apply('thinking-loop')
    }, secondsOf('thinking-intro'))
  }, [apply, clearTimer, secondsOf])

  /** 正文开始输出：不等答案生成完，直接从思考切到讲解 */
  const startExplaining = useCallback(() => {
    clearTimer()
    apply('explaining')
    cycleStartRef.current = Date.now()
    cycleMsRef.current = secondsOf('explaining')
    timerRef.current = window.setTimeout(() => {
      if (actionRef.current !== 'explaining') return
      if (!streamingRef.current) { apply('idle'); return }
      /* 还在写：接一小段往复，避免 10s 正片播完后就干站着 */
      apply('explaining-loop')
      cycleStartRef.current = Date.now()
      cycleMsRef.current = secondsOf('explaining-loop')
    }, cycleMsRef.current)
  }, [apply, clearTimer, secondsOf])

  /** 输出结束：把当前这一轮播完再回待机，别半截掐断 */
  const finishExplaining = useCallback(() => {
    clearTimer()
    const cycle = cycleMsRef.current || secondsOf('explaining')
    const elapsed = Date.now() - cycleStartRef.current
    const remain = cycle - (elapsed % cycle)
    timerRef.current = window.setTimeout(() => apply('idle'), Math.max(0, remain))
  }, [apply, clearTimer, secondsOf])

  useEffect(() => {
    const prev = prevStatusRef.current
    prevStatusRef.current = status

    if (status === 'thinking') {
      if (prev !== 'thinking') playThinking()
      return
    }
    if (prev === null) return
    if (prev === 'thinking') {
      if (status === 'error') { playOnce('error'); return }
      if (actionRef.current === 'explaining' || actionRef.current === 'explaining-loop') {
        finishExplaining()
        return
      }
      /* 一轮提问结束但全程没吐字（被中断 / 空回答）：直接回待机。
         讲解只由「真的开始输出正文」触发，避免状态抖动时误播 10s 讲解。 */
      clearTimer()
      apply('idle')
      return
    }
    /* 没经过思考就直接失败（重试按钮、历史里最后一条是失败等） */
    if (status === 'error' && prev !== 'error') playOnce('error')
  }, [status, playThinking, playOnce, finishExplaining])

  /* 吐字即讲解：只从「思考动作」切过去，不打断出错/行礼 */
  useEffect(() => {
    if (!streaming || status !== 'thinking') return
    const current = actionRef.current
    if (current === 'thinking-intro' || current === 'thinking-loop') startExplaining()
  }, [streaming, status, startExplaining])

  /* 悬停 3 秒打招呼：只在待机时触发，不打断正在播的动作 */
  useEffect(() => {
    if (!hovered) return
    const timer = window.setTimeout(() => {
      if (actionRef.current === 'idle') playOnce('greet')
    }, PET_HOVER_GREET_DELAY)
    return () => window.clearTimeout(timer)
  }, [hovered, playOnce])

  /* 彩蛋插播：按 nonce 判定"新命令"，播一次后照常回待机 */
  const commandNonce = command?.nonce ?? 0
  useEffect(() => {
    if (!command || !commandNonce) return
    playOnce(command.action)
    // command 内容随 nonce 一起变，用 nonce 作唯一触发条件
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commandNonce])

  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  return { action, src: petActionSrc(action) }
}
