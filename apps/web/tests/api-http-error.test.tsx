import { afterEach, expect, test, vi } from 'vitest'

import { ApiError, readableDetail, request } from '../src/api/http'

/**
 * 回归：FastAPI 的 422 校验错误是 detail 数组，旧实现会把它 String() 成
 * "[object Object]"，用户根本看不出哪里错了。
 */

afterEach(() => vi.unstubAllGlobals())

function stubFetch(status: number, body: string) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
  })))
}

test('readableDetail：422 数组错误拼成人话', () => {
  const body = JSON.stringify({
    detail: [{
      type: 'literal_error',
      loc: ['body', 'teacher_persona'],
      msg: "Input should be 'vodyanitsa'",
      input: 'elf',
    }],
  })
  expect(readableDetail(body)).toBe("请求参数不合法：teacher_persona Input should be 'vodyanitsa'")
})

test('readableDetail：字符串 detail / 纯文本 / 空体都能兜住', () => {
  expect(readableDetail(JSON.stringify({ detail: '课程不存在' }))).toBe('课程不存在')
  expect(readableDetail('<html>502 Bad Gateway</html>')).toBe('<html>502 Bad Gateway</html>')
  expect(readableDetail('')).toBe('')
  expect(readableDetail(JSON.stringify({ detail: { msg: '字段缺失' } }))).toBe('字段缺失')
})

test('request：非 2xx 抛 ApiError，消息可读且带状态码', async () => {
  stubFetch(422, JSON.stringify({ detail: [{ loc: ['body', 'question'], msg: '长度不足' }] }))
  await expect(request('/api/x')).rejects.toMatchObject({
    name: 'ApiError',
    message: 'question：长度不足',
    status: 422,
  })
  await expect(request('/api/x')).rejects.toBeInstanceOf(ApiError)
})

test('request：响应体不是 JSON 时给出可读提示', async () => {
  stubFetch(200, '<!doctype html><p>gateway</p>')
  await expect(request('/api/x')).rejects.toThrow('服务响应异常（非 JSON），请稍后重试')
})
