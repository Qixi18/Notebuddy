import { afterEach, expect, test, vi } from 'vitest'
import { courseApi } from '../src/api/courses'
import { materialApi } from '../src/api/materials'
import { streamAgentMessage } from '../src/api/agent'
import { ApiError, request } from '../src/api/http'

afterEach(() => vi.unstubAllGlobals())

// Captured from the isolated FastAPI server for POST /courses { name: '' }.
const invalidCourse = { detail: [{ type: 'string_too_short', loc: ['body', 'name'], msg: 'String should have at least 1 character', input: '', ctx: { min_length: 1 } }] }
const invalidQuestion = { detail: [{ type: 'string_too_short', loc: ['body', 'question'], msg: 'String should have at least 1 character', input: '', ctx: { min_length: 1 } }] }

function respond(body: unknown, status: number) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })))
}

test('course validation errors identify the invalid field rather than coercing FastAPI errors to objects', async () => {
  respond(invalidCourse, 422)
  await expect(courseApi.createCourse('')).rejects.toMatchObject({
    name: 'ApiError', status: 422, message: 'name：String should have at least 1 character',
  })
})

test('failed document parsing exposes the backend message from structured detail', async () => {
  respond({ detail: { code: 'parse_failed', message: '资料解析失败，请重新解析' } }, 409)
  await expect(materialApi.getAssetDocument('asset', 'notebook')).rejects.toMatchObject({
    name: 'ApiError', status: 409, message: '资料解析失败，请重新解析',
  })
})

test('agent HTTP validation errors use the same readable error contract', async () => {
  respond(invalidQuestion, 422)
  await expect(streamAgentMessage('missing', { question: '', scope: 'course' }, {})).rejects.toMatchObject({
    name: 'ApiError', status: 422, message: 'question：String should have at least 1 character',
  })
})

test.each([
  [{ detail: '课程不存在' }, '课程不存在'],
  [{ detail: [{ loc: ['body', 'answers', 0, 'answer'], msg: 'Field required' }, { loc: ['query', 'limit'], msg: 'Input should be greater than or equal to 1' }] }, 'answers.0.answer：Field required\nlimit：Input should be greater than or equal to 1'],
])('ordinary and multiple validation errors retain their useful messages', async (body, message) => {
  respond(body, 422)
  await expect(request('/test')).rejects.toMatchObject({ message, status: 422 })
})

test('plain-text and empty upstream failures remain readable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('服务暂不可用', { status: 503 })).mockResolvedValueOnce(new Response('', { status: 502 })))
  await expect(request('/test')).rejects.toThrow('服务暂不可用')
  await expect(request('/test')).rejects.toEqual(new ApiError('请求失败：502', 502))
})
