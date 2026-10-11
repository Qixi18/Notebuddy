import { useEffect, useRef, useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { featurePath, useWorkspace } from '../components/AppLayout'
import { SourceCard } from '../components/SourceCard'
import { TeacherCharacter, type TeacherStatus } from '../components/TeacherCharacter'
import { teacherPersonaMeta } from '../features/persona/personas'
import { api } from '../api'

/* 回答模式标签，取值与后端 app.ai.orchestrator 的 mode 一一对应 */
const modeLabels: Record<string, string> = {
  'deepseek-rag': 'AI 生成 · 参考当前课程来源',
  'persona-general': '未匹配课程资料 · 老师通用回答',
  'local-retrieval-fallback': '本地检索结果 · 模型回答暂不可用',
}

const noEvidenceLabels: Record<string, string> = {
  'persona-general': '这轮没有命中课程页面，回答只是老师的通用说明，不能当作课件依据。',
  'no-evidence': '当前课程资料没有找到直接依据，联网补充也不可用；请缩小问题范围或先上传相关课件。',
  'local-retrieval-fallback': '模型当前不可用，下面是分层检索得到的原文摘录。',
}

export function AssistantPage() {
  const {
    course,
    courseId,
    materials,
    courseContentLoading,
    selectedMaterialId,
    setSelectedMaterialId,
    pages,
    setSelectedPageNumber,
    teacherPersona,
    conversation,
  } = useWorkspace()
  const { ask, ready: conversationReady, busy: conversationBusy, messages } = conversation
  const navigate = useNavigate()
  const location = useLocation()
  const chatEndRef = useRef<HTMLDivElement>(null)
  const initialQuestionSent = useRef(false)
  const [webStatus, setWebStatus] = useState<{ configured: boolean; status: string }>({ configured: false, status: 'unconfigured' })
  const [draft, setDraft] = useState('')
  const [assistantMaterialId, setAssistantMaterialId] = useState<string>()
  const [assistantPageNumber, setAssistantPageNumber] = useState<number>()
  const [pendingInitialQuestion, setPendingInitialQuestion] = useState<string>()
  const [learningGoal, setLearningGoal] = useState('理解概念')
  const [feedbackSaved, setFeedbackSaved] = useState<string>()
  const [term, setTerm] = useState('')
  const [discipline, setDiscipline] = useState('')
  const [termExplanation, setTermExplanation] = useState<Awaited<ReturnType<typeof api.explainTerm>>>()
  const [termBusy, setTermBusy] = useState(false)
  const [termError, setTermError] = useState<string>()

  useEffect(() => { setAssistantMaterialId(undefined); setAssistantPageNumber(undefined) }, [courseId])
  useEffect(() => { void api.getWebSearchStatus().then(setWebStatus).catch(() => setWebStatus({ configured: false, status: 'unavailable' })) }, [])

  /* 首页「问 AI」带来的问题：等会话就绪后走同一条落库链路 */
  useEffect(() => {
    const state = location.state as { initialQuestion?: unknown } | null
    if (typeof state?.initialQuestion !== 'string' || !state.initialQuestion.trim()) return
    initialQuestionSent.current = false
    setPendingInitialQuestion(state.initialQuestion.trim())
    navigate(location.pathname, { replace: true, state: null })
  }, [location.key, location.pathname, location.state, navigate])

  useEffect(() => {
    if (!pendingInitialQuestion || !conversationReady || initialQuestionSent.current) return
    const text = pendingInitialQuestion
    initialQuestionSent.current = true
    setPendingInitialQuestion(undefined)
    void ask(text, { materialId: assistantMaterialId, pageNumber: assistantPageNumber, learningGoal })
      .then((sent) => { if (!sent) setDraft(text) })
  }, [pendingInitialQuestion, conversationReady, ask, assistantMaterialId, assistantPageNumber, learningGoal])

  async function explainTerm(event: FormEvent) {
    event.preventDefault()
    if (!courseId || !term.trim() || termBusy) return
    try {
      setTermBusy(true)
      setTermError(undefined)
      setTermExplanation(await api.explainTerm(courseId, term.trim(), discipline.trim() || undefined))
    } catch (cause) {
      setTermError(cause instanceof Error ? cause.message : '术语解释失败')
      setTermExplanation(undefined)
    } finally {
      setTermBusy(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || conversationBusy) return
    setDraft('')
    void ask(text, { materialId: assistantMaterialId, pageNumber: assistantPageNumber, learningGoal })
      .then((sent) => { if (!sent) setDraft(text) })
  }

  const lastAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant')
  const hasAsked = messages.some((message) => message.role === 'user')
  const teacherStatus: TeacherStatus = conversationBusy
    ? 'thinking'
    : lastAssistantMessage?.status === 'failed' ? 'error'
      : hasAsked ? 'explaining' : 'idle'

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  return (
    <div className="feature-page page-enter assistant-page">
      <header className="page-heading-block compact-heading">
        <div><span className="eyebrow">{course?.name ?? '当前课程'}</span><h1>AI 课程答疑</h1><p>回答优先依据当前课程已解析页面，并展示检索到的课件来源。</p></div>
          <span className="assistant-mode-pill"><span className="local-status-dot" />课程资料优先 · 回答附来源</span>
      </header>

      <section className="assistant-workspace" aria-label="课程答疑对话">
        <div className="assistant-context-bar">
          <TeacherCharacter status={teacherStatus} compact character={teacherPersona} />
          <div><strong>{teacherPersonaMeta(teacherPersona).name} · 教学助手</strong><small>当前课程：{course?.name ?? '未选择课程'}</small><span className="assistant-teacher-status" aria-live="polite" aria-atomic="true">{conversationBusy ? '正在检索本课程内容并组织回答…' : teacherStatus === 'error' ? '刚才的回答未能完成，可稍后重试' : teacherStatus === 'explaining' ? (lastAssistantMessage?.mode === 'persona-general' ? '这轮没有命中课程页面，老师只作了通用说明' : '已根据课程内容生成回答') : '等待你的课程问题'}</span></div>
          <details className="assistant-options">
            <summary>答疑设置</summary>
            <div className="assistant-options-grid">
              <label className="assistant-material-scope">限定资料
                <select value={assistantMaterialId ?? ''} onChange={(event) => { const id = event.target.value || undefined; setAssistantMaterialId(id); if (id) setSelectedMaterialId(id); setAssistantPageNumber(undefined) }}>
                  <option value="">整门课程</option>
                  {materials.map((material) => <option key={material.id} value={material.id}>{material.lecture_title}</option>)}
                </select>
              </label>
              <label className="assistant-material-scope">会话
                <select value={conversation.conversationId ?? ''} onChange={(event) => void conversation.selectConversation(event.target.value)} aria-label="选择答疑会话">
                  {conversation.conversations.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
                </select>
              </label>
              <label className="assistant-material-scope">学习目标
                <select value={learningGoal} onChange={(event) => setLearningGoal(event.target.value)}><option>理解概念</option><option>准备复习</option><option>解决练习</option><option>比较方法</option></select>
              </label>
              {assistantMaterialId && <label className="assistant-material-scope">限定页面<select value={assistantPageNumber ?? ''} onChange={(event) => setAssistantPageNumber(event.target.value ? Number(event.target.value) : undefined)}><option value="">整份资料</option>{assistantMaterialId === selectedMaterialId && pages.map((page) => <option value={page.page_number} key={page.id}>第 {page.page_number} 页 · {page.title ?? '未识别标题'}</option>)}</select></label>}
            </div>
            <details className="assistant-term-panel">
              <summary>术语原文说明</summary>
              <p>输入课程中的术语，查看原文、常见译法和学科语境。没有可核验出处时会明确标记不确定。</p>
              <form onSubmit={(event) => void explainTerm(event)}>
                <input value={term} onChange={(event) => setTerm(event.target.value)} maxLength={200} placeholder="例如：dependency injection" aria-label="术语" />
                <input value={discipline} onChange={(event) => setDiscipline(event.target.value)} maxLength={100} placeholder="学科（可选）" aria-label="学科" />
                <button className="secondary-button" type="submit" disabled={!term.trim() || termBusy}>{termBusy ? '查询中…' : '解释术语'}</button>
              </form>
              {termError && <p className="form-error" role="alert">{termError}</p>}
              {termExplanation && <div className={`term-explanation ${termExplanation.uncertain ? 'term-explanation-uncertain' : ''}`} role="status"><strong>{termExplanation.original}{termExplanation.discipline ? ` · ${termExplanation.discipline}` : ''}</strong>{termExplanation.common_translations.length > 0 && <span>常见译法：{termExplanation.common_translations.join('、')}</span>}<p>{termExplanation.explanation}</p><small>{termExplanation.source_note}{termExplanation.uncertain ? ' · 不确定' : ''}</small>{termExplanation.sources?.map((source) => <small key={`${source.material_id}-${source.page_number}`}>课程来源：{source.lecture_title} · 第 {source.page_number} 页 · {source.snippet}</small>)}</div>}
            </details>
          </details>
        </div>

        <div className="assistant-conversation" aria-live="polite">
          {messages.map((message, index) => (
            <article className={`conversation-message conversation-${message.role}`} key={`${message.id}-${index}`}>
              <span className="conversation-author">{message.role === 'assistant' ? teacherPersonaMeta(teacherPersona).name : '你'}</span>
              {message.role === 'assistant' ? <div className="assistant-answer-content"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{message.content}</ReactMarkdown></div> : <p>{message.content}</p>}
              {message.role === 'assistant' && message.status !== 'failed' && message.mode ? <span className="answer-mode-label">{modeLabels[message.mode] ?? '当前课程资料检索'}</span> : null}
              {message.role === 'assistant' && message.status !== 'failed' && message.mode && !(message.sources?.length) ? <span className="answer-no-evidence">{noEvidenceLabels[message.mode] ?? '这次回答没有找到可直接引用的课程页面。'}</span> : null}
              {message.evidence.length > 0 && <details className="answer-evidence-details"><summary>查看详细依据 · {message.evidence.length}</summary><div className="answer-evidence-list">{message.evidence.map((item) => <small key={item.id}>{item.claim_key} · {item.evidence_type} · {item.location_label ?? '来源位置'} · {item.support_level}</small>)}</div></details>}
              {message.role === 'assistant' && message.status !== 'failed' && message.id !== 'local-greeting' && <div className="answer-feedback-actions"><button type="button" onClick={() => courseId && void api.saveFeedback(courseId, { target_type: 'assistant_message', target_id: message.id, category: 'helpful' }).then(() => setFeedbackSaved(message.id))}>有帮助</button><button type="button" onClick={() => courseId && void api.saveFeedback(courseId, { target_type: 'assistant_message', target_id: message.id, category: 'not_helpful' }).then(() => setFeedbackSaved(message.id))}>需改进</button>{feedbackSaved === message.id && <small>反馈已保存</small>}</div>}
              {message.sources?.length ? (
                <div className="answer-sources"><span>回答依据 · 课程课件与网络补充（分开标注）</span>
                  {message.sources.map((source) => (
                    source.source_type === 'web' && source.url ? <a className="source-card web-source-card" key={source.url} href={source.url} target="_blank" rel="noreferrer"><span className="source-card-icon">↗</span><span className="source-card-body"><small className="source-card-meta">网络补充 · {source.site_name} · {source.published_at ? `发布于 ${source.published_at}` : ''} · 检索于 {source.retrieved_at ? new Date(source.retrieved_at).toLocaleDateString('zh-CN') : '刚刚'}</small><strong>{source.title}</strong><small>{source.snippet}</small></span></a> : source.material_id && source.page_number ? <SourceCard key={`${source.material_id}-${source.page_number}`} title={source.lecture_title ?? '课程资料'} pageNumber={source.page_number} quote={source.snippet} onOpen={() => {
                      openMaterialSource(source.material_id!, source.page_number ?? undefined)
                      if (courseId) navigate(featurePath(courseId, 'materials'))
                    }} /> : null
                  ))}
                </div>
              ) : null}
            </article>
          ))}
          <div ref={chatEndRef} />
        </div>

        {courseContentLoading ? <div className="assistant-no-materials" role="status">正在读取课程资料…</div> : materials.length === 0 && <div className="assistant-no-materials">这门课程还没有资料。上传并解析课件后，答疑才能引用课程内容。{courseId && <Link className="secondary-button link-button" to={featurePath(courseId, 'materials')}>去上传课程资料</Link>}</div>}
        <form className="assistant-question-form" onSubmit={handleSubmit}>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="问问当前课程……" rows={3} aria-label="课程问题" />
          <div className="assistant-question-footer"><span>课程检索限定当前课程；{webStatus.configured ? '网络结果会与课件来源分开标注。' : '未配置 Tavily 时只检索课程资料。'}</span><button className="primary-button" type="submit" disabled={!draft.trim() || conversationBusy}>{conversationBusy ? '正在思考…' : '发送问题'} <span aria-hidden="true">↑</span></button></div>
        </form>
      </section>
    </div>
  )
}
