import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { featurePath, useWorkspace } from '../components/AppLayout'
import { TeacherCharacter, type TeacherStatus } from '../components/TeacherCharacter'
import { teacherPersonaMeta } from '../features/persona/personas'
import { modeLabels, noEvidenceLabels } from '../features/assistant/answerMeta'
import { AssistantMessageMarkdown, AssistantMessageSource } from '../features/assistant/AssistantMessageContent'
import { api } from '../api'

function PetMark() {
  return (
    <svg className="pet-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4.3 12.3c2.9-3.8 7.5-4.8 11.8-2.4 1.1.6 2 1.5 2.7 2.6-1 .4-1.9.6-2.9.6-4.2 0-8-.3-11.6-.8Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M18.3 13.2c1.5-1.5 3-2.1 4.4-2-.5 1.5-1.3 2.7-2.5 3.8" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="7.3" cy="11.7" r=".9" fill="currentColor" />
    </svg>
  )
}

function ThreadSkeleton() {
  return (
    <div className="pet-thread-skeleton" role="status" aria-label="正在准备答疑">
      <span />
      <span />
      <span />
    </div>
  )
}

export function AssistantPage() {
  const {
    course,
    courseId,
    materials,
    notes,
    courseContentLoading,
    selectedMaterialId,
    setSelectedMaterialId,
    pages,
    openMaterialSource,
    teacherPersona,
    conversation,
  } = useWorkspace()
  const { ask, ready: conversationReady, busy: conversationBusy, messages } = conversation
  const navigate = useNavigate()
  const location = useLocation()
  const threadRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
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

  function useStarter(prompt: string) {
    setDraft(prompt)
    inputRef.current?.focus()
  }

  const persona = teacherPersonaMeta(teacherPersona)
  const lastAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant')
  const hasAsked = messages.some((message) => message.role === 'user')
  const teacherStatus: TeacherStatus = conversationBusy
    ? 'thinking'
    : lastAssistantMessage?.status === 'failed' ? 'error'
      : hasAsked ? 'explaining' : 'idle'
  const statusCopy = conversationBusy
    ? '正在翻课程资料…'
    : lastAssistantMessage?.status === 'failed' ? '刚才没答上来，可以再试一次'
      : hasAsked ? '刚回答完，回答里标了出处'
        : '等待你的问题'
  const scopeLabel = assistantMaterialId
    ? materials.find((material) => material.id === assistantMaterialId)?.lecture_title ?? '限定资料'
    : '整门课程'
  const starterPrompts = materials.length
    ? [
      '这门课最重要的三个概念是什么？',
      '用一句话解释这一讲的核心定义。',
      '帮我把这一讲整理成复习提纲。',
    ]
    : [
      '这门课可以按什么顺序学？',
      '帮我列出这门课需要先掌握的基础。',
      '我该怎么开始整理第一份课件？',
    ]

  useEffect(() => {
    /* 只滚对话容器，不调用 scrollIntoView —— 后者在移动端会把整页往下拽一屏。 */
    const node = threadRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages.length, conversationBusy])

  return (
    <div className="feature-page page-enter assistant-page pet-page">
      <div className="pet-studio">
        <aside className="pet-nook" aria-label="桌宠与答疑设置">
          <div className="pet-nook-head">
            <span className="eyebrow">DESK PET · 桌宠</span>
            <button
              className="pet-new-thread"
              type="button"
              disabled={conversationBusy || !courseId}
              onClick={() => void conversation.startNewConversation()}
            >＋ 新对话</button>
          </div>

          <div className="pet-stage">
            <span className="pet-stage-ripple" aria-hidden="true" />
            <TeacherCharacter status={teacherStatus} animated character={teacherPersona} />
          </div>

          <div className="pet-identity">
            <h2>{persona.name}</h2>
            <p>{persona.title} · 教学助手</p>
            <span className={`pet-status${conversationBusy ? ' is-busy' : ''}`} aria-live="polite" aria-atomic="true"><i aria-hidden="true" />{statusCopy}</span>
          </div>

          <div className="pet-course">
            <span className="pet-mini-label">当前课程</span>
            <strong>{course?.name ?? '未选择课程'}</strong>
            {courseId && <Link to={`/courses/${courseId}`}>课程概览 <span aria-hidden="true">→</span></Link>}
          </div>

          <div className="pet-course-stats" aria-label="课程资料与笔记数量">
            <span><b>{courseContentLoading ? '…' : materials.length}</b> 份资料</span>
            <span><b>{courseContentLoading ? '…' : notes.length}</b> 条笔记</span>
          </div>

          <details className="pet-settings">
            <summary>答疑设置</summary>
            <div className="pet-settings-grid">
              <label className="pet-field">限定资料
                <select value={assistantMaterialId ?? ''} onChange={(event) => {
                  const id = event.target.value || undefined
                  setAssistantMaterialId(id)
                  if (id) setSelectedMaterialId(id)
                  setAssistantPageNumber(undefined)
                }}>
                  <option value="">整门课程</option>
                  {materials.map((material) => <option key={material.id} value={material.id}>{material.lecture_title}</option>)}
                </select>
              </label>
              <label className="pet-field">会话
                <select value={conversation.conversationId ?? ''} onChange={(event) => void conversation.selectConversation(event.target.value)} aria-label="选择答疑会话">
                  {conversation.conversations.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
                </select>
              </label>
              <label className="pet-field">学习目标
                <select value={learningGoal} onChange={(event) => setLearningGoal(event.target.value)}>
                  <option>理解概念</option>
                  <option>准备复习</option>
                  <option>解决练习</option>
                  <option>比较方法</option>
                </select>
              </label>
              {assistantMaterialId && (
                <label className="pet-field">限定页面
                  <select value={assistantPageNumber ?? ''} onChange={(event) => setAssistantPageNumber(event.target.value ? Number(event.target.value) : undefined)}>
                    <option value="">整份资料</option>
                    {assistantMaterialId === selectedMaterialId && pages.map((page) => (
                      <option value={page.page_number} key={page.id}>第 {page.page_number} 页 · {page.title ?? '未识别标题'}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            <details className="pet-term">
              <summary>术语原文说明</summary>
              <p>输入课程中的术语，查看原文、常见译法和学科语境。没有可核验出处时会明确标记不确定。</p>
              <form onSubmit={(event) => void explainTerm(event)}>
                <input value={term} onChange={(event) => setTerm(event.target.value)} maxLength={200} placeholder="例如：dependency injection" aria-label="术语" />
                <input value={discipline} onChange={(event) => setDiscipline(event.target.value)} maxLength={100} placeholder="学科（可选）" aria-label="学科" />
                <button className="secondary-button" type="submit" disabled={!term.trim() || termBusy}>{termBusy ? '查询中…' : '解释术语'}</button>
              </form>
              {termError && <p className="form-error" role="alert">{termError}</p>}

              {termExplanation && (
                <div className={`pet-term-result${termExplanation.uncertain ? ' is-uncertain' : ''}`} role="status">
                  <strong>{termExplanation.original}{termExplanation.discipline ? ` · ${termExplanation.discipline}` : ''}</strong>
                  {termExplanation.common_translations.length > 0 && <span>常见译法：{termExplanation.common_translations.join('、')}</span>}
                  <p>{termExplanation.explanation}</p>
                  <small>{termExplanation.source_note}{termExplanation.uncertain ? ' · 不确定' : ''}</small>
                  {termExplanation.sources?.map((source) => (
                    <small key={`${source.material_id}-${source.page_number}`}>课程来源：{source.lecture_title} · 第 {source.page_number} 页 · {source.snippet}</small>

                  ))}
                </div>
              )}
            </details>
          </details>

          <p className="pet-nook-note">在首页、资料页或森林里，也可以从右下角叫我。</p>
        </aside>

        <section className="pet-room" aria-label="课程答疑对话">
          <header className="pet-room-head">
            <div>
              <span className="eyebrow">{course?.name ?? '当前课程'} · 答疑桌宠</span>
              <h1>问{persona.name}</h1>
              <p>它会先翻这门课的资料，再回答你；找不到依据时会明说。</p>
            </div>
            <span className="pet-source-pill"><span className="local-status-dot" aria-hidden="true" />课程资料优先 · 回答附来源</span>
          </header>

          <div className="pet-thread" role="log" aria-live="polite" aria-busy={conversationBusy} aria-label="答疑对话" ref={threadRef}>
            {!conversationReady ? <ThreadSkeleton /> : messages.length === 1 && messages[0].id === 'local-greeting' ? (
              <div className="pet-welcome">
                <div className="pet-welcome-note">
                  <span className="pet-welcome-mark" aria-hidden="true"><PetMark /></span>
                  <div>
                    <span>{persona.name}</span>
                    <p>{messages[0].content}</p>
                  </div>
                </div>
                <div className="pet-starters">
                  <span className="eyebrow">可以从这里开始</span>
                  {starterPrompts.map((prompt) => (
                    <button key={prompt} type="button" onClick={() => useStarter(prompt)}>
                      <span>{prompt}</span><span aria-hidden="true">→</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : messages.map((message, index) => (
              message.role === 'assistant' ? (
                <article className="pet-msg pet-msg-assistant" key={`${message.id}-${index}`}>
                  <span className="pet-msg-mark" aria-hidden="true"><PetMark /></span>
                  <div className="pet-msg-body">
                    <header>
                      <span>{persona.name}</span>
                      {message.mode && <em>{modeLabels[message.mode] ?? '当前课程资料检索'}</em>}
                    </header>
                    <div className="pet-answer">
                      <AssistantMessageMarkdown content={message.content} />
                    </div>
                    {message.status !== 'failed' && message.mode && !(message.sources?.length) && (
                      <span className="pet-no-evidence">{noEvidenceLabels[message.mode] ?? '这次回答没有找到可直接引用的课程页面。'}</span>
                    )}
                    {message.evidence.length > 0 && (
                      <details className="pet-evidence">
                        <summary>查看详细依据 · {message.evidence.length}</summary>
                        <div>
                          {message.evidence.map((item) => <small key={item.id}>{item.claim_key} · {item.evidence_type} · {item.location_label ?? '来源位置'} · {item.support_level}</small>)}
                        </div>
                      </details>
                    )}
                    {message.sources?.length ? (
                      <div className="pet-sources">
                        <span>回答依据 · 课程课件与网络补充分开标注</span>
                        {message.sources.map((source, sourceIndex) => (
                          <AssistantMessageSource
                            key={`${source.source_ref_id ?? source.url ?? source.material_id}-${sourceIndex}`}
                            source={source}
                            onOpen={source.material_id && source.page_number ? () => {
                              openMaterialSource(source.material_id!, source.page_number ?? undefined)
                              if (courseId) navigate(featurePath(courseId, 'materials'))
                            } : undefined}
                          />
                        ))}
                      </div>
                    ) : null}
                    {message.role === 'assistant' && message.status !== 'failed' && message.id !== 'local-greeting' && (
                      <div className="pet-feedback">
                        <button type="button" onClick={() => courseId && void api.saveFeedback(courseId, { target_type: 'assistant_message', target_id: message.id, category: 'helpful' }).then(() => setFeedbackSaved(message.id))}>有帮助</button>
                        <button type="button" onClick={() => courseId && void api.saveFeedback(courseId, { target_type: 'assistant_message', target_id: message.id, category: 'not_helpful' }).then(() => setFeedbackSaved(message.id))}>需改进</button>
                        {feedbackSaved === message.id && <small>反馈已保存</small>}
                      </div>
                    )}
                  </div>
                </article>
              ) : (
                <article className="pet-msg pet-msg-user" key={`${message.id}-${index}`}>
                  <span>你</span>
                  <p>{message.content}</p>
                </article>
              )
            ))}
          </div>

          {courseContentLoading ? <p className="pet-inline-status" role="status">正在读取课程资料…</p> : materials.length === 0 && (
            <div className="pet-no-materials">
              <span>这门课还没有可检索的资料。上传并解析课件后，回答才会引用课程内容。</span>
              {courseId && <Link to={featurePath(courseId, 'materials')}>去上传课程资料 <span aria-hidden="true">→</span></Link>}
            </div>
          )}
          {conversation.error && <p className="pet-error" role="alert">{conversation.error}</p>}

          <form className="pet-composer" onSubmit={handleSubmit}>
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={`问${persona.name}任何关于「${course?.name ?? '当前课程'}」的问题……`}
              rows={2}
              aria-label="课程问题"
            />
            <div className="pet-composer-foot">
              <span className="pet-composer-hint">{webStatus.configured ? '只检索当前课程 · 网络补充单独标注' : '只检索当前课程 · 网络补充未启用'}</span>
              <div className="pet-composer-actions">
                <span className="pet-scope-chip">{scopeLabel}</span>
                <button className="primary-button" type="submit" disabled={!draft.trim() || conversationBusy}>
                  {conversationBusy ? '正在翻资料…' : '发送'} <span aria-hidden="true">↑</span>
                </button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </div>
  )
}
