import { useSyncExternalStore } from 'react'

import type { TeacherCharacterId } from '../../components/TeacherCharacter'
import {
  DEFAULT_TEACHER_PERSONA,
  TEACHER_PERSONA_ORDER,
} from './personas'

const STORAGE_KEY = 'nb-teacher-character'

function isTeacherCharacterId(value: unknown): value is TeacherCharacterId {
  return typeof value === 'string' && (TEACHER_PERSONA_ORDER as readonly string[]).includes(value)
}

function readStored(): TeacherCharacterId {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (isTeacherCharacterId(saved)) return saved
  } catch {
    /* localStorage 不可用时回落到默认老师 */
  }
  return DEFAULT_TEACHER_PERSONA
}

let current: TeacherCharacterId = readStored()
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): TeacherCharacterId {
  return current
}

function write(next: TeacherCharacterId) {
  if (next === current) return
  current = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* 存储写入失败时不阻断本次切换 */
  }
  listeners.forEach((listener) => listener())
}

/** 同一账号多标签页之间同步选中的老师 */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY || !isTeacherCharacterId(event.newValue)) return
    write(event.newValue)
  })
}

export function setTeacherCharacter(next: TeacherCharacterId) {
  write(next)
}

/** 首页 ⇄ 按钮：在三位老师之间循环切换 */
export function cycleTeacherCharacter() {
  const index = TEACHER_PERSONA_ORDER.indexOf(current)
  write(TEACHER_PERSONA_ORDER[(index + 1) % TEACHER_PERSONA_ORDER.length] ?? DEFAULT_TEACHER_PERSONA)
}

/**
 * 全局共享的当前 AI 教师。首页、答疑页、悬浮答疑坞读到的是同一份状态，
 * 因此切换后立即对所有提问生效。
 */
export function useTeacherCharacter(): [TeacherCharacterId, typeof setTeacherCharacter] {
  const character = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  return [character, setTeacherCharacter]
}
