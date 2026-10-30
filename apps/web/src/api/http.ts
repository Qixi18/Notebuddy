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
