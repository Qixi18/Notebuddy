/**
 * localStorage 防御包装（v6 P4）：隐私模式 / 禁用存储时抛 SecurityError，
 * 外壳初始化裸 getItem 会直接炸掉整个应用。读写全部静默降级——
 * 持久化失败只影响「记住状态」，不该阻断功能。
 */
export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // 设置不可用时静默降级
  }
}
