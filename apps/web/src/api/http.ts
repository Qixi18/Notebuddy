export async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  if (!response.ok) {
    throw await readApiError(response)
  }
  // 204 No Content / 空响应体（如 DELETE 会话）不能再调用 response.json()，
  // 否则会因「unexpected end of JSON input」抛错，让本已成功的操作表现为失败。
  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text.trim()) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError('服务响应异常（非 JSON），请稍后重试', response.status)
  }
}

/** FastAPI returns string details, validation arrays, or domain errors with a message. */
export async function readApiError(response: Response): Promise<ApiError> {
  const body = await response.text()
  let detail: unknown
  try {
    detail = (JSON.parse(body) as { detail?: unknown } | null)?.detail
  } catch {
    // Keep plain-text upstream error bodies readable.
  }
  let message = body
  if (typeof detail === 'string') message = detail
  else if (Array.isArray(detail)) {
    message = detail.flatMap((error: unknown) => {
      if (!error || typeof error !== 'object' || !('msg' in error) || typeof error.msg !== 'string') return []
      const path = 'loc' in error && Array.isArray(error.loc)
        ? error.loc.filter((part, index) => index !== 0 || !['body', 'query', 'path', 'header'].includes(part)).join('.')
        : ''
      return [path ? `${path}：${error.msg}` : error.msg]
    }).join('\n') || body
  } else if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') {
    message = detail.message
  }
  return new ApiError(message || `请求失败：${response.status}`, response.status)
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * 同步版可读化：把 FastAPI 的错误体解析成人能读的句子。
 *
 * FastAPI 的参数校验错误长这样：`{"detail":[{"loc":["body","teacher_persona"],"msg":"..."}]}`，
 * 旧实现把 `detail` 直接丢给 Error 构造函数，数组里的对象被 String() 成
 * `[object Object]`，用户只看到这串天书。这里按结构拼装；解析不了就原样返回。
 *
 * 与上面的 {@link readApiError} 并存：后者是请求路径实际使用的（异步读 body），
 * 本函数供需要先拿到 body 再自行拼装的调用方使用。
 */
export function readableDetail(body: string): string {
  if (!body) return ''
  let parsed: unknown
  try {
    parsed = JSON.parse(body)
  } catch {
    return body // 网关返回的纯文本 / HTML 片段，保持原样
  }
  const detail = (parsed as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item
      const entry = item as { loc?: unknown; msg?: unknown } | null
      const loc = Array.isArray(entry?.loc)
        ? entry.loc.filter((part) => part !== 'body' && part !== 'query').join('.')
        : ''
      const msg = typeof entry?.msg === 'string' ? entry.msg : ''
      if (msg && loc) return `${loc} ${msg}`
      return msg
    }).filter(Boolean)
    return parts.length ? `请求参数不合法：${parts.join('；')}` : ''
  }
  if (detail && typeof detail === 'object' && typeof (detail as { msg?: unknown }).msg === 'string') {
    return (detail as { msg: string }).msg
  }
  return ''
}
