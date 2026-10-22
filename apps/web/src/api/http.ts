export async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  if (!response.ok) {
    const body = await response.text()
    let detail = body
    try {
      const parsed = JSON.parse(body) as { detail?: string }
      detail = parsed.detail ?? body
    } catch {
      // Keep plain-text upstream error bodies readable.
    }
    throw new ApiError(detail || `请求失败：${response.status}`, response.status)
  }
  // 204 No Content / 空响应体（如 DELETE 会话）不能再调用 response.json()，
  // 否则会因「unexpected end of JSON input」抛错，让本已成功的操作表现为失败。
  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text.trim()) return undefined as T
  return JSON.parse(text) as T
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}
