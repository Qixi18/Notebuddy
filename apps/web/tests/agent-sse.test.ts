import assert from 'node:assert/strict'
import { test } from 'node:test'

import { parseAgentStream } from '../src/api/agentStream.ts'

test('parseAgentStream 拆出完整帧并保留余量', () => {
  const buffer = 'data: {"type":"delta","text":"你"}\n\ndata: {"type":"delta","text":"好"}\n\ndata: {"type"'
  const { events, rest } = parseAgentStream(buffer)

  assert.deepEqual(events, [
    { type: 'delta', text: '你' },
    { type: 'delta', text: '好' },
  ])
  assert.equal(rest, 'data: {"type"')
})

test('parseAgentStream 分派五类事件', () => {
  const frames = [
    'data: {"type":"step","tool":"search_course","detail":"检索「导数」","status":"running"}\n\n',
    'data: {"type":"step","tool":"search_course","detail":"命中 3 条","status":"done"}\n\n',
    'data: {"type":"delta","text":"回答"}\n\n',
    'data: {"type":"notice","text":"已切换标准模式"}\n\n',
    'data: {"type":"final","answer":"回答","mode":"agent","sources":[],"suggestions":[]}\n\n',
    'data: {"type":"error","message":"失败"}\n\n',
  ].join('')
  const { events } = parseAgentStream(frames)

  assert.deepEqual(events.map((event) => event.type), ['step', 'step', 'delta', 'notice', 'final', 'error'])
  const step = events[0] as { tool: string; status: string }
  assert.equal(step.tool, 'search_course')
  assert.equal(step.status, 'running')
})

test('parseAgentStream 忽略坏帧与非 data 行，不断流', () => {
  const { events } = parseAgentStream(
    'event: ping\n\n: comment\n\ndata: 不是json{{\n\ndata: {"type":"delta","text":"ok"}\n\n',
  )
  assert.deepEqual(events, [{ type: 'delta', text: 'ok' }])
})

test('parseAgentStream 兼容被规范化成 \r\n\r\n 的帧边界（v6 P2）', () => {
  const buffer = 'data: {"type":"delta","text":"你"}\r\n\r\ndata: {"type":"delta","text":"好"}\r\n\r\ndata: {"type"'
  const { events, rest } = parseAgentStream(buffer)

  assert.deepEqual(events, [
    { type: 'delta', text: '你' },
    { type: 'delta', text: '好' },
  ])
  assert.equal(rest, 'data: {"type"')
})

test('parseAgentStream 混合行尾也能逐帧拆出', () => {
  const { events } = parseAgentStream(
    'data: {"type":"delta","text":"a"}\n\ndata: {"type":"delta","text":"b"}\r\n\r\ndata: {"type":"delta","text":"c"}\n\r\n',
  )
  assert.deepEqual(events.map((event) => (event as { text: string }).text), ['a', 'b', 'c'])
})
