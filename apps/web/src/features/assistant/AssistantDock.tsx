import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { featurePath, useWorkspace } from '../../components/AppLayout'
import { TeacherCharacter } from '../../components/TeacherCharacter'
import { api } from '../../api'
import type { AgentNotebookContext, AgentReadingContext, AgentScope } from '../../api/agent'
import { useNotebookBridge } from '../notebook-editor/NotebookBridge'
import type { AIAction, SelectionAnchor } from '../notebook-editor/NotebookEditor'
import type { Material } from '../../types'
import { teacherPersonaMeta } from '../persona/personas'
import { modeLabelsShort } from './answerMeta'
import { AgentSteps } from './AgentSteps'
import { useNotebookEditSuggestions } from './useNotebookEditSuggestions'
import { AssistantMessageMarkdown, AssistantMessageSource } from './AssistantMessageContent'
import { KnowledgeProposalCards, NotebookEditSuggestionCards } from './AgentCards'

import {
  clampDockWidth,
  DOCK_WIDTH_DEFAULT,
  DOCK_WIDTH_SNAP,
  DOCK_WIDTH_STEP,
} from './dockLayout'

type AssistantDockProps = {
  /** 当前宽度，由外壳持有并持久化 */
  width: number
  onWidthChange: (width: number) => void
  onClose: () => void
  /** 拖拽期间通知外壳关掉过渡并禁用选中，避免宽度落后鼠标 */
  onResizeStateChange: (resizing: boolean) => void
  /** 笔记页选区工具条请求的快捷动作；消费后由外壳清空 */
  notebookAction?: AIAction | null
  onNotebookActionConsumed?: () => void
}

/** 参考项目悬浮坞的三个快捷提示，对应「解释 / 检索 / 总结」三能力 */
const QUICK_PROMPTS: Array<{ label: string; prompt: string }> = [
  { label: '解释概念', prompt: '用更直白的话解释一下这里的核心概念，并举一个例子。' },
  { label: '检索课件', prompt: '课程资料里还有哪些相关内容？请标出出处。' },
  { label: '总结要点', prompt: '把主要内容总结成几条要点。' },
]

/**
 * 悬浮答疑坞。与答疑页共用 useConversation 的同一份会话，
 * 因此这里问过的问题会落库，切到答疑页也能看到完整历史。
 *
 * 抽屉形态与能力参照 notebuddy_myself 的「伴读智能体」悬浮坞：
 *   · 不是浮层遮罩，而是主内容区右侧的挤压式抽屉，展开时正文自动让位；
 *   · 左边缘分界条可拖拽实时调宽（双击复位、拖太窄自动收合、宽度记忆）；
 *   · 上下文感知：说明当前挂在哪门课 / 哪份课件上，范围可手动收窄；
 *   · 检索显性化：回答后附来源清单，可跳回课件；
 *   · Notebook 编辑：选区采纳会检查 Notebook revision 与锚点，正式建议经过审核后写入。
 */
export function AssistantDock({ width, onWidthChange, onClose, onResizeStateChange, notebookAction, onNotebookActionConsumed }: AssistantDockProps) {
  const {
    courseId,
    courses,
    conversationCourseId,
    materials: workspaceMaterials,
    openMaterialSource,
    teacherPersona,
    conversation,
  } = useWorkspace()
  const navigate = useNavigate()
  const [draft, setDraft] = useState('')
  /** 作用范围：整门课程 / 全局可查 / 具体 material id；Notebook 正文以独立上下文传递。 */
  const [scopeChoice, setScopeChoice] = useState<string>('')
  const [ownMaterials, setOwnMaterials] = useState<Material[]>([])
  /** 已采纳建议 id → 采纳前正文（一键撤销用） */
  const messagesRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const persona = teacherPersonaMeta(teacherPersona)
  const conversationCourse = courses.find((item) => item.id === conversationCourseId)
  const fellBackToRecent = Boolean(conversationCourseId) && !courseId
  const notebook = useNotebookBridge()
  const activeConversation = conversation.conversations?.find((item) => item.id === conversation.conversationId)
  const scopeLocked = conversation.hasMessages === true
  const persistedScope = scopeLocked ? activeConversation?.scope : undefined
  const [pendingNotebookAnswer, setPendingNotebookAnswer] = useState<{
    courseId: string
    notebookId: string
    revision: number
    editVersion: number
    anchor: SelectionAnchor | null
    previousAnswerId: string | undefined
  } | null>(null)
  const [adoptNotice, setAdoptNotice] = useState<string>()

  useEffect(() => {
    if (!notebookAction) return
    const prompts: Record<AIAction, string> = {
      explain: '请解释我在笔记中选中的这段内容，说清它在当前课程里的含义。',
      summarize: '请把我在笔记中选中的这段内容总结成几条要点。',
      expand: '请基于我在笔记中选中的这段内容扩写，补充必要的推导或例子。',
      example: '请针对我在笔记中选中的这段内容生成一道例题，并给出解题思路。',
    }
    setDraft(prompts[notebookAction])
    onNotebookActionConsumed?.()
    window.setTimeout(() => inputRef.current?.focus(), 80)
  }, [notebookAction, onNotebookActionConsumed])

  /* 课程页上工作区已经加载了同一门课的资料，直接复用；其余页面（首页、回收站…）自己拉一份，
     否则「限定资料」在那些页面上会是空的 */
  const reusingWorkspaceMaterials = Boolean(conversationCourseId) && conversationCourseId === courseId
  useEffect(() => {
    if (!conversationCourseId || reusingWorkspaceMaterials) { setOwnMaterials([]); return }
    let active = true
    void api.listMaterials(conversationCourseId)
      .then((items) => { if (active) setOwnMaterials(items) })
      .catch(() => { if (active) setOwnMaterials([]) })
    return () => { active = false }
  }, [conversationCourseId, reusingWorkspaceMaterials])
  const scopeMaterials = reusingWorkspaceMaterials ? workspaceMaterials : ownMaterials
  /* 范围落不到实处时收回「整门课程」，而不是让请求带着一个已失效的 id */
  useEffect(() => {
    if (scopeChoice && scopeChoice !== '__global__'
      && !scopeMaterials.some((item) => item.id === scopeChoice)) setScopeChoice('')
  }, [scopeChoice, scopeMaterials])

  /* 作用范围三档：锁定当前笔记 / 整门课程（可再收窄到课件）/ 全局可查。
     锁定档要求「正打开着笔记的页面」，否则选项自动失效落回课程档 */
  const scope: AgentScope = persistedScope === 'note' ? 'note'
    : persistedScope === 'global' ? 'global'
      : scopeChoice === '__global__' ? 'global' : 'course'
  const agentMaterialId = scope === 'course' && scopeChoice && scopeChoice !== '__global__'
    ? scopeChoice
    : undefined
  const messages = conversation.messages
  const lastMessage = messages[messages.length - 1]
  const lastAnswer = [...messages].reverse().find((message) => message.role === 'assistant' && message.id !== 'local-greeting')
  const finalAnswerId = conversation.agentRun?.final?.message_id
  const adoptableAnswer = pendingNotebookAnswer && notebook && !conversation.busy && finalAnswerId
    && lastAnswer?.id === finalAnswerId && finalAnswerId !== pendingNotebookAnswer.previousAnswerId
    && notebook.courseId === pendingNotebookAnswer.courseId
    && notebook.notebookId === pendingNotebookAnswer.notebookId ? lastAnswer : null
  const hasAsked = messages.some((message) => message.role === 'user')
  /* 范围锁定：会话已有真实问答后，后端不再按本轮改 scope（api/v1/agent.py:91 只在首轮落库） */
  const streamingTextLength = conversation.agentRun?.streamingText.length ?? 0
  const bottomKey = `${messages.length}:${lastMessage?.content.length ?? 0}:${conversation.busy}:${streamingTextLength}:${conversation.agentRun?.steps.length ?? 0}`


  /* 消息变化后重新定位视口：agent 流式执行期间跟随底部（步骤与正文持续增长），
     其余情况把新回复的开头对齐到顶部（读到的是正文开头） */
  useEffect(() => {
    const node = messagesRef.current
    if (!node) return
    if (conversation.agentRun && !conversation.agentRun.final) {
      node.scrollTop = node.scrollHeight
      return
    }
    const last = node.lastElementChild as HTMLElement | null
    if (last?.classList.contains('assistant-dock-message-assistant')) {
      node.scrollTop += Math.round(last.getBoundingClientRect().top - node.getBoundingClientRect().top) - 2
    } else {
      node.scrollTop = node.scrollHeight
    }
  }, [bottomKey, conversation.agentRun])

  /* 外壳总宽：上限比例要按它算，否则窄窗口下抽屉能把正文挤没。
     拿不到外壳（理论上不会）时退回窗口宽度。 */
  function containerWidth(grip: HTMLElement): number {
    const shell = grip.closest('.app-shell')
    return shell instanceof HTMLElement && shell.clientWidth > 0 ? shell.clientWidth : window.innerWidth
  }

  /* 拖拽用 pointer 事件：鼠标 / 触控 / 触控笔一套手势。
     监听挂在 window 上，指针滑出那条 12px 细线也不会中断拖拽。 */
  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    const grip = event.currentTarget
    const startX = event.clientX
    const startWidth = width
    /* 原始值单独记一份：clamp 会把宽度托到下限，收合判定必须看用户手上真实的拖动量 */
    let rawWidth = startWidth
    try {
      grip.setPointerCapture?.(event.pointerId)
    } catch {
      /* jsdom 等环境未实现指针捕获，忽略即可，拖拽本身不依赖它 */
    }
    onResizeStateChange(true)

    const handleMove = (moveEvent: PointerEvent) => {
      rawWidth = startWidth - (moveEvent.clientX - startX) // 往左拖 = 变宽
      onWidthChange(clampDockWidth(rawWidth, containerWidth(grip)))
    }
    const handleEnd = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleEnd)
      window.removeEventListener('pointercancel', handleEnd)
      onResizeStateChange(false)
      if (rawWidth < DOCK_WIDTH_SNAP) {
        // 拖得太窄：视为「我要关掉它」，宽度记回默认值，下次唤起仍是舒服的尺寸
        onWidthChange(DOCK_WIDTH_DEFAULT)
        onClose()
      }
    }
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleEnd)
    window.addEventListener('pointercancel', handleEnd)
  }

  function nudgeWidth(event: ReactKeyboardEvent<HTMLDivElement>) {
    const grip = event.currentTarget
    if (event.key === 'ArrowLeft') onWidthChange(clampDockWidth(width + DOCK_WIDTH_STEP, containerWidth(grip)))
    else if (event.key === 'ArrowRight') onWidthChange(clampDockWidth(width - DOCK_WIDTH_STEP, containerWidth(grip)))
    else if (event.key === 'Home') onWidthChange(DOCK_WIDTH_DEFAULT)
    else return
    event.preventDefault()
  }

  async function submitQuestion(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!conversationCourseId || !text || conversation.busy) return
    setDraft('')
    setAdoptNotice(undefined)
    if (notebook && notebook.courseId
      && (scope !== 'note' || !scopeLocked || activeConversation?.note_id === notebook.notebookId)) {
      setPendingNotebookAnswer({
        courseId: notebook.courseId, notebookId: notebook.notebookId,
        revision: notebook.revision, editVersion: notebook.editVersion,
        anchor: notebook.selection, previousAnswerId: lastAnswer?.id,
      })
    } else setPendingNotebookAnswer(null)
    let notebookContext: AgentNotebookContext | undefined = notebook && notebook.courseId ? {
      course_id: notebook.courseId,
      notebook_id: notebook.notebookId,
      revision: notebook.revision,
      title: notebook.title.slice(0, 200),
      selection: notebook.selection?.text.slice(0, 4000),
      excerpt: notebook.excerpt,
    } : undefined
    let effectiveReadingContext: AgentReadingContext | undefined = notebook
      ? { note_title: notebook.title, excerpt: notebook.excerpt } : undefined
    if (scope === 'note' && activeConversation?.note_id && conversationCourseId) {
      try {
        const lockedDocument = await api.getNotebookDocument(conversationCourseId, activeConversation.note_id)
        notebookContext = {
          course_id: conversationCourseId, notebook_id: activeConversation.note_id,
          revision: lockedDocument.revision, title: activeConversation.note_title ?? notebook?.title,
          excerpt: lockedDocument.blocks.map((block) => block.text).join('\n').slice(0, 1200),
        }
        effectiveReadingContext = { note_title: activeConversation.note_title ?? notebook?.title,
          excerpt: notebookContext.excerpt }
      } catch (cause) {
        setDraft(text)
        setPendingNotebookAnswer(null)
        setAdoptNotice(cause instanceof Error ? cause.message : '无法读取锁定的 Notebook')
        return
      }
    }
    if (!await conversation.askAgent(text, {
      scope: notebook?.courseId && !scopeLocked ? 'course' : scope,
      materialId: agentMaterialId,
      readingContext: effectiveReadingContext,
      notebookContext,
    })) { setDraft(text); setPendingNotebookAnswer(null) }
  }

  function adoptAnswer(mode: 'after' | 'replace') {
    if (!notebook || !adoptableAnswer || !pendingNotebookAnswer?.anchor) return
    const ok = notebook.insertAI(adoptableAnswer.content, mode, pendingNotebookAnswer.anchor,
      pendingNotebookAnswer.revision, pendingNotebookAnswer.editVersion)
    setAdoptNotice(ok
      ? mode === 'replace' ? '已替换选区内容，正文保存后生效。' : '已插入到选区之后，正文保存后生效。'
      : '选区已经变化，未能自动写入。请回到正文重新选择，或复制内容后手动粘贴。')
  }

  /* Notebook 的待确认建议持久化在服务端，桌宠与答疑页共用同一状态机。 */
  const lastAgentFinalId = conversation.agentRun?.final?.message_id
  const notebookSuggestions = useNotebookEditSuggestions({
    target: notebook?.courseId ? {
      courseId: notebook.courseId,
      notebookId: notebook.notebookId,
      title: notebook.title,
      revision: notebook.revision,
      editVersion: notebook.editVersion,
      isDirty: notebook.isDirty,
      adoptDocument: notebook.adoptDocument,
    } : null,
    agentFinalId: lastAgentFinalId,
  })

  /* 来源卡片只在「抽屉挂靠的课程 == 当前浏览的课程」时可点：
     否则跳过去会带着另一门课的页码，把用户引到错的地方 */
  const sourcesOpenable = Boolean(courseId) && conversationCourseId === courseId

  const rangeLabel = persistedScope === 'note'
    ? `锁定《${activeConversation?.note_title ?? notebook?.title ?? 'Notebook'}》`
    : scopeChoice === '__global__'
      ? '全局可查'
      : agentMaterialId
        ? `课件《${scopeMaterials.find((item) => item.id === agentMaterialId)?.lecture_title ?? '未命名'}》`
        : '整门课程'
  const contextLabel = persistedScope === 'note'
    ? `锁定《${activeConversation?.note_title ?? 'Notebook'}》`
    : notebook
    ? `整篇笔记《${notebook.title}》${notebook.selection ? ` · 选中 ${notebook.selection.text.replace(/\s/g, '').length} 字` : ''}`
    : rangeLabel

  return (
    <aside className="assistant-dock" aria-label="课程学习助手">
      <div
        className="assistant-dock-grip"
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整答疑坞宽度，双击复位"
        title="拖拽调整宽度 · 双击复位"
        tabIndex={0}
        onPointerDown={startResize}
        onDoubleClick={() => onWidthChange(DOCK_WIDTH_DEFAULT)}
        onKeyDown={nudgeWidth}
      ><i /><i /><i /></div>

      <header className="assistant-dock-heading">
        <span className="assistant-dock-avatar" aria-hidden="true">
          <TeacherCharacter compact animated status={conversation.busy ? 'thinking' : 'idle'} character={teacherPersona} />
        </span>
        <div><strong>{persona.name} · 伴读桌宠</strong><small>{conversationCourse?.name ?? '尚无可提问的课程'}</small></div>
        <button className="assistant-dock-close" type="button" onClick={onClose} aria-label="收起答疑坞" title="收起答疑坞">×</button>
      </header>

      {conversationCourseId ? (
        <>
          {/* 上下文行：说明这轮问答挂在哪门课、哪个范围上，落回最近课程时讲清原因 */}
          <p className="assistant-dock-context" aria-live="polite">
            上下文：<strong>「{conversationCourse?.name ?? '课程'}」</strong> · {contextLabel}
            {fellBackToRecent ? <em>（按最近访问自动选定）</em> : null}
          </p>

          <label className="assistant-dock-scope">作用范围
            <select value={persistedScope === 'note' ? '__note__' : persistedScope === 'global' ? '__global__' : scopeChoice}
              onChange={(event) => setScopeChoice(event.target.value)} aria-label="本次提问的作用范围">
              {/* 范围是会话级属性：首条消息之后后端不再改写 scope，
                  所以这三档在会话开始提问后就禁用，避免「标签变了、回答范围没变」。
                  课件收窄是消息级参数（material_id 只校验不锁定），保持可选。 */}
              {persistedScope === 'note' ? <option value="__note__" disabled>📌 锁定《{activeConversation?.note_title ?? 'Notebook'}》</option> : null}
              <option value="" disabled={scopeLocked}>整门课程</option>
              {scopeMaterials.map((material) => <option key={material.id} value={material.id}>{material.lecture_title}</option>)}
              <option value="__global__" disabled={scopeLocked}>🌲 全局可查（跨课程）</option>
            </select>
          </label>
          {scopeLocked ? (
            <p className="assistant-dock-scope-lock" role="status">🔒 范围已锁定（首条消息后不能改）；仍可限定到某份课件。</p>
          ) : null}
          {notebook ? <p className="assistant-dock-open-hint">正在编辑整篇笔记：选中文字后提问，回答可以直接插入或替换选区，采纳前不会改动正文。</p> : null}

          <div className="assistant-dock-messages" aria-live="polite" ref={messagesRef}>
            {messages.map((message, index) => (
              <article className={`assistant-dock-message assistant-dock-message-${message.role}`} key={`${message.role}-${index}-${message.content.slice(0, 12)}`}>
                <small>{message.role === 'user' ? '你' : persona.name}</small>
                {/* 老师回答走与答疑页同一条 Markdown 管线（remark-math + rehype-katex），
                    否则 ### / ** / 列表会以原始标记直接显示出来；自己的提问保持纯文本 */}
                {message.role === 'assistant'
                  ? <div className="assistant-dock-answer"><AssistantMessageMarkdown content={message.content} /></div>
                  : <p>{message.content}</p>}
                {/* 检索能力显性化：说清这轮是否命中了课件 */}
                {message.role === 'assistant' && message.mode ? <span className="assistant-dock-mode">{modeLabelsShort[message.mode] ?? '课程资料检索'}</span> : null}
                {message.role === 'assistant' && message.sources?.length ? (
                  <div className="assistant-dock-sources">
                    <small>回答依据 · {message.sources.length} 条</small>
                    {message.sources.map((source, sourceIndex) => (
                      <AssistantMessageSource
                        key={`${source.source_ref_id ?? source.url ?? source.material_id}-${sourceIndex}`}
                        source={source}
                        onOpen={sourcesOpenable && source.notebook_id && courseId ? () => {
                          const params = new URLSearchParams()
                          if (source.asset_id) {
                            params.set('asset', source.asset_id)
                            if (source.page_number) params.set('page', String(source.page_number))
                          } else if (source.block_id) params.set('section', source.block_id)
                          navigate(`/courses/${courseId}/notebooks/${source.notebook_id}${params.size ? `?${params}` : ''}`)
                        } : sourcesOpenable && source.material_id && source.page_number ? () => {
                          openMaterialSource(source.material_id!, source.page_number ?? undefined)
                          if (courseId) navigate(featurePath(courseId, 'materials'))
                        } : undefined}
                      />
                    ))}
                  </div>
                ) : null}
              </article>
            ))}

            {!hasAsked && (
              <div className="assistant-dock-start">
                <p>可以先问我这些</p>
                {QUICK_PROMPTS.map((item) => (
                  <button key={item.label} type="button" disabled={conversation.busy} onClick={() => { setDraft(item.prompt); inputRef.current?.focus() }}>
                    <span>{item.label}</span><span aria-hidden="true">→</span>
                  </button>
                ))}
              </div>
            )}
            {/* agent 执行中的实时块：步骤时间线 + 流式回答；final 到达后由历史消息接管，不再重复展示。
                被用户中断时保留已收到的正文，但标题改成「已中断」，不再假装还在执行。 */}
            {conversation.agentRun && !conversation.agentRun.final ? (
              <article className={`assistant-dock-message assistant-dock-message-assistant assistant-dock-live${conversation.agentRun.aborted ? ' is-aborted' : ''}`}>
                <small>{conversation.agentRun.aborted ? `${persona.name} · 已中断` : persona.name}</small>
                <AgentSteps steps={conversation.agentRun.steps} />
                {conversation.agentRun.notice ? <p className="assistant-dock-agent-notice">{conversation.agentRun.notice}</p> : null}
                {conversation.agentRun.streamingText ? (
                  <div className="assistant-dock-answer assistant-dock-streaming">
                    <AssistantMessageMarkdown content={conversation.agentRun.streamingText} />
                    {conversation.agentRun.aborted ? null : <span className="assistant-dock-cursor" aria-hidden="true" />}
                  </div>
                ) : null}
              </article>
            ) : null}
          </div>

          {conversation.agentRun?.final?.suggestions?.some((item) => item.type === 'knowledge_proposal') ? (
            <KnowledgeProposalCards
              suggestions={conversation.agentRun.final.suggestions.filter((item): item is Extract<typeof item, { type: 'knowledge_proposal' }> => item.type === 'knowledge_proposal')}
            />
          ) : null}
          {notebook?.courseId ? <NotebookEditSuggestionCards
            suggestions={notebookSuggestions.suggestions}
            busyId={notebookSuggestions.busyId}
            onReview={(item, decision, indices) => void notebookSuggestions.review(item, decision, indices)}
          /> : null}

          {hasAsked && <div className="assistant-dock-quick">
            {QUICK_PROMPTS.map((item) => (
              <button key={item.label} type="button" disabled={conversation.busy} onClick={() => { setDraft(item.prompt); inputRef.current?.focus() }}>{item.label}</button>
            ))}
          </div>}


          {notebook && adoptableAnswer ? <section className="assistant-dock-adopt" aria-label="采纳 AI 建议">
            <div className="assistant-dock-adopt-head"><strong>AI 建议</strong><small>采纳前不会写入笔记</small></div>
            <div className="assistant-dock-adopt-actions">
              <button type="button" onClick={() => adoptAnswer('after')} disabled={!pendingNotebookAnswer?.anchor}>插入到选区后</button>
              <button type="button" onClick={() => adoptAnswer('replace')} disabled={!pendingNotebookAnswer?.anchor}>替换选区</button>
              <button type="button" onClick={() => { void navigator.clipboard.writeText(adoptableAnswer.content).then(() => setAdoptNotice('回答已复制。')) }}>复制</button>
            </div>
            {adoptNotice ? <p role="status">{adoptNotice}</p> : null}
          </section> : null}

          <form className="assistant-dock-form" onSubmit={submitQuestion}>
            <textarea ref={inputRef} aria-label="快速提问" placeholder={`问问「${conversationCourse?.name ?? '当前课程'}」…`} value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} />
            <div className="assistant-dock-actions">
              <button type="button" className="assistant-dock-ghost" disabled={conversation.busy} onClick={() => { setAdoptNotice(undefined); void conversation.startNewConversation() }}>新建对话</button>
              {conversation.busy ? (
                <button type="button" className="assistant-dock-stop" onClick={() => conversation.stopAgent?.()}>停止</button>
              ) : (
                <button type="submit" className="assistant-dock-send" disabled={!draft.trim()}>发送</button>
              )}
            </div>
            <div className="assistant-dock-links"><Link to={featurePath(conversationCourseId, 'assistant')}>打开完整答疑</Link></div>
          </form>

          {(adoptNotice || notebookSuggestions.notice || conversation.error) && (
            <p className={`assistant-dock-status${(adoptNotice || notebookSuggestions.notice) && !conversation.error ? '' : ' assistant-dock-status-error'}`} role="status">
              {conversation.error ?? adoptNotice ?? notebookSuggestions.notice}
            </p>
          )}
        </>
      ) : (
        <div className="assistant-dock-empty">
          <p>还没有可提问的课程。创建课程并上传学习资料后，悬浮坞就能基于课件回答。</p>
          <Link className="text-button" to="/">创建课程</Link>
        </div>
      )}
    </aside>
  )
}
