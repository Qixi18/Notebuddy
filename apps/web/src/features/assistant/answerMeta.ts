/**
 * 回答模式与「没有依据」的文案。
 * 答疑页与悬浮坞都要展示同一套说法，放这里避免两边漂移。
 * 取值与后端 app.ai.orchestrator 的 mode 一一对应。
 */

export const modeLabels: Record<string, string> = {
  'deepseek-rag': 'AI 生成 · 参考当前课程来源',
  'persona-general': '未匹配课程资料 · 老师通用回答',
  'local-retrieval-fallback': '本地检索结果 · 模型回答暂不可用',
  'agent': '智能模式 · agent 已检索资料并执行',
}

export const noEvidenceLabels: Record<string, string> = {
  'persona-general': '这轮没有命中课程页面，回答只是老师的通用说明，不能当作课件依据。',
  'no-evidence': '当前课程资料没有找到直接依据，联网补充也不可用；请缩小问题范围或先上传相关课件。',
  'local-retrieval-fallback': '模型当前不可用，下面是分层检索得到的原文摘录。',
}

/** 悬浮坞里更短的说法（窄栏放不下整句） */
export const modeLabelsShort: Record<string, string> = {
  'deepseek-rag': '依据课程课件',
  'persona-general': '未命中课件 · 通用回答',
  'local-retrieval-fallback': '本地检索摘录',
  'agent': 'Agent 智能模式',
}
