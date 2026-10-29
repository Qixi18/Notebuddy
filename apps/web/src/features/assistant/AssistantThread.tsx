import { useEffect, useRef, useState, type ReactNode } from 'react'

import type { ConversationMessage } from '../../types'
import { modeLabels, noEvidenceLabels } from './answerMeta'
import { AgentSteps } from './AgentSteps'
import { AgentThinking } from './AgentThinking'
import { MessageSkillCards } from './AgentCards'
import { AssistantMessageMarkdown } from './AssistantMessageContent'
import { CitationText } from './CitationText'
import { SourcesRow } from './SourcesRow'
import type { AgentRunState } from '../conversation/useConversation'

function PetMark() {
  return (
    <svg className="workspace-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4.3 12.3c2.9-3.8 7.5-4.8 11.8-2.4 1.1.6 2 1.5 2.7 2.6-1 .4-1.9.6-2.9.6-4.2 0-8-.3-11.6-.8Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M18.3 13.2c1.5-1.5 3-2.1 4.4-2-.5 1.5-1.3 2.7-2.5 3.8" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="7.3" cy="11.7" r=".9" fill="currentColor" />
    </svg>
  )
}

function ThreadSkeleton() {
  return (
    <div className="workspace-thread-skeleton" role="status" aria-label="正在准备答疑">
      <span />
      <span />
      <span />
    </div>
  )
}

function messageTimeLabel(message: ConversationMessage): string {
  if (!message.created_at) return ''
  const time = Date.parse(message.created_at)
  if (Number.isNaN(time)) return ''
  return new Date(time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

/** 复制到剪贴板：优先用 async clipboard，非安全上下文降级到 execCommand */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 落到降级路径 */
  }
  if (typeof document.execCommand !== 'function') return false
  try {
    const holder = document.createElement('textarea')
    holder.value = text
    holder.setAttribute('readonly', '')
    holder.style.position = 'fixed'
    holder.style.opacity = '0'
    document.body.appendChild(holder)
    holder.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(holder)
    return ok
  } catch {
    return false
  }
}

/** 追问建议：点一下只把话术填进输入框，由用户决定要不要发 */
const FOLLOW_UPS = ['再展开讲讲', '能举个例子吗', '这和上一讲有什么关系'] as const

function AnswerCard({ message, personaName, onFeedback, onOpenMaterial, onOpenNotebook, onRetry, retryText, onFollowUp, skillCourseId, onSkillAsk }: {
  message: ConversationMessage
  personaName: string
  onFeedback: (messageId: string, category: 'helpful' | 'not_helpful') => Promise<boolean>
  onOpenMaterial?: (materialId: string, page: number) => void
  onOpenNotebook?: (notebookId: string, blockId?: string, assetId?: string, page?: number) => void
  /** 失败卡的重试：回传原问题原文，由调用方重发 */
  onRetry?: (text: string) => void
  /** 可重试的原问题原文 */
  retryText?: string
  /** 追问 chips：只填草稿，不自动发送 */
  onFollowUp?: (prompt: string) => void
  skillCourseId?: string
  onSkillAsk?: (prompt: string) => void
}) {
  const [activeNo, setActiveNo] = useState<number>()
  /* 每次点击角标都递增序号：同一个角标连点两次也要能重新定位（只靠 activeNo 不会触发副作用） */
  const [citeFocus, setCiteFocus] = useState<{ no: number; seq: number }>()
  const citeSeq = useRef(0)
  const [feedbackSaved, setFeedbackSaved] = useState(false)
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const sources = message.sources ?? []

  function handleCite(no: number) {
    setActiveNo(no)
    citeSeq.current += 1
    setCiteFocus({ no, seq: citeSeq.current })
  }

  async function handleFeedback(category: 'helpful' | 'not_helpful') {
    if (feedbackBusy) return
    setFeedbackBusy(true)
    const saved = await onFeedback(message.id, category)
    setFeedbackBusy(false)
    if (saved) setFeedbackSaved(true)
  }

  async function handleCopy() {
    const ok = await copyText(message.content)
    if (!ok) return
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <article className={`workspace-msg workspace-msg-assistant${message.status === 'failed' ? ' is-failed' : ''}`}>
      <span className="workspace-msg-mark" aria-hidden="true"><PetMark /></span>
      <div className="workspace-msg-body">
        <header className="workspace-msg-head">
          <strong>{personaName}</strong>
          {message.mode && <em>{modeLabels[message.mode] ?? '课程资料检索'}</em>}
          {messageTimeLabel(message) && <time>{messageTimeLabel(message)}</time>}
        </header>

        <div className="workspace-msg-content">
          <CitationText content={message.content} sources={sources} onCite={handleCite} />
        </div>

        {message.process ? <details className="message-process">
          <summary>过程记录{message.process.steps.length ? ` · ${message.process.steps.length} 个步骤` : ''}</summary>
          {message.process.thinking ? <pre className="agent-thinking-body agent-thinking-body-open">{message.process.thinking}</pre> : null}
          <AgentSteps steps={message.process.steps.map((step) => ({
            type: 'step' as const, tool: step.tool, detail: step.detail,
            duration_ms: step.duration_ms, status: 'done' as const,
          }))} />
        </details> : null}
        <MessageSkillCards suggestions={message.suggestions ?? []} courseId={skillCourseId} onAsk={onSkillAsk} />

        {message.status !== 'failed' && message.mode && sources.length === 0 && (
          <span className="workspace-msg-noevidence">
            {noEvidenceLabels[message.mode] ?? '这次回答没有找到可直接引用的课程页面。'}
          </span>
        )}
        {message.status === 'failed' && (
          <div className="workspace-msg-failed">
            <span className="workspace-msg-noevidence">刚才没答上来，可以换个问法再试一次。</span>
            {onRetry && retryText ? (
              <button type="button" className="workspace-msg-retry" onClick={() => onRetry(retryText)}>
                重试
              </button>
            ) : null}
          </div>
        )}

        <SourcesRow
          content={message.content}
          sources={sources}
          activeNo={activeNo}
          focus={citeFocus}
          onActive={setActiveNo}
          onOpenMaterial={onOpenMaterial}
          onOpenNotebook={onOpenNotebook}
        />

        {message.status !== 'failed' && message.id !== 'local-greeting' && (
          <footer className="workspace-msg-foot">
            <div className="workspace-msg-feedback">
              <button
                type="button"
                disabled={feedbackBusy}
                aria-pressed={feedbackSaved}
                onClick={() => void handleFeedback('helpful')}
              >有帮助</button>
              <button
                type="button"
                disabled={feedbackBusy}
                aria-pressed={feedbackSaved}
                onClick={() => void handleFeedback('not_helpful')}
              >需改进</button>
              {feedbackSaved && <small>反馈已保存</small>}
            </div>
            <button type="button" className="workspace-msg-copy" onClick={() => void handleCopy()}>
              {copied ? '已复制' : '复制'}
            </button>
          </footer>
        )}

        {message.status !== 'failed' && message.id !== 'local-greeting' && onFollowUp && (
          <div className="workspace-msg-chips">
            {FOLLOW_UPS.map((prompt) => (
              <button key={prompt} type="button" onClick={() => onFollowUp(prompt)}>{prompt}</button>
            ))}
          </div>
        )}
      </div>
    </article>
  )
}

/** 对话主线：欢迎态 / 用户气泡 / 回答卡（角标 + 依据行 + 反馈）/ agent 实时块 */
export function AssistantThread({ ready, busy, messages, conversationId, personaName, starters, onStarter, onFeedback, onOpenMaterial, onOpenNotebook, onRetry, onFollowUp, agentRun, extras, skillCourseId, onSkillAsk }: {
  ready: boolean
  busy: boolean
  messages: ConversationMessage[]
  conversationId?: string
  personaName: string
  starters: string[]
  onStarter: (prompt: string) => void
  onFeedback: (messageId: string, category: 'helpful' | 'not_helpful') => Promise<boolean>
  onOpenMaterial?: (materialId: string, page: number) => void
  onOpenNotebook?: (notebookId: string, blockId?: string, assetId?: string, page?: number) => void
  /** 失败卡的重试：回传原问题原文，由调用方重发 */
  onRetry?: (text: string) => void
  /** 追问 chips：只把话术填进草稿，不自动发送 */
  onFollowUp?: (prompt: string) => void
  /** agent 执行中的实时状态：步骤时间线 + 流式正文（final 到达后由历史消息接管） */
  agentRun?: AgentRunState | null
  /** 对话流末尾的附加内容（agent 产出的建议卡片等） */
  extras?: ReactNode
  skillCourseId?: string
  onSkillAsk?: (prompt: string) => void
}) {
  const threadRef = useRef<HTMLDivElement>(null)
  const prevConversation = useRef<string | undefined>(undefined)
  const prevCount = useRef(0)
  /* 流式正文长度：消息条数不变时，靠它判断「还在长」 */
  const liveLength = agentRun?.streamingText.length ?? 0

  /* 失败卡要重试的是它前面那条提问：往上找最近的一条 user 消息 */
  function retryTextFor(index: number): string | undefined {
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') return messages[i].content
    }
    return undefined
  }

  useEffect(() => {
    /* 只滚对话容器，不调用 scrollIntoView —— 后者在移动端会把整页往下拽一屏。 */
    const node = threadRef.current
    if (!node) return
    const delta = messages.length - prevCount.current
    const conversationChanged = prevConversation.current !== conversationId
    prevConversation.current = conversationId
    prevCount.current = messages.length

    const answers = node.querySelectorAll<HTMLElement>('.workspace-msg-assistant')
    const last = answers[answers.length - 1]
    /* 有提问气泡就停在提问处，让「问 + 答」一起进入视野 */
    const previous = last?.previousElementSibling
    const anchor = previous instanceof HTMLElement && previous.classList.contains('workspace-msg-user') ? previous : last

    /* 切会话，或一次载入整段历史（不是逐条新增）：落到最后一条问答的开头 */
    if ((conversationChanged || delta > 1) && anchor) {
      node.scrollTop += Math.round(anchor.getBoundingClientRect().top - node.getBoundingClientRect().top) - 10
      return
    }
    /* 逐条新增（提问 / 回答）或流式正文增长时跟到底部 */
    if (delta > 0 || busy || liveLength > 0) node.scrollTop = node.scrollHeight
  }, [messages.length, busy, conversationId, liveLength])

  return (
    <div className="workspace-thread" role="log" aria-live="polite" aria-busy={busy} aria-label="答疑对话" ref={threadRef}>
      {!ready ? <ThreadSkeleton /> : messages.length === 1 && messages[0].id === 'local-greeting' ? (
        <div className="workspace-welcome">
          <div className="workspace-welcome-note">
            <span className="workspace-welcome-mark" aria-hidden="true"><PetMark /></span>
            <div>
              <span>{personaName}</span>
              <p>{messages[0].content}</p>
            </div>
          </div>
          <div className="workspace-starters">
            <span className="eyebrow">可以从这里开始</span>
            {starters.map((prompt) => (
              <button key={prompt} type="button" onClick={() => onStarter(prompt)}>
                <span>{prompt}</span><span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        </div>
      ) : messages.map((message, index) => (
        message.role === 'assistant' ? (
          <AnswerCard
            key={`${message.id}-${index}`}
            message={message}
            personaName={personaName}
            onFeedback={onFeedback}
            onOpenMaterial={onOpenMaterial}
            onOpenNotebook={onOpenNotebook}
            onRetry={onRetry}
            retryText={retryTextFor(index)}
            onFollowUp={onFollowUp}
            skillCourseId={skillCourseId}
            onSkillAsk={onSkillAsk}
          />
        ) : (
          <article className="workspace-msg workspace-msg-user" key={`${message.id}-${index}`}>
            {messageTimeLabel(message) && <time>{messageTimeLabel(message)}</time>}
            <span aria-hidden="true">你</span>
            <p>{message.content}</p>
          </article>
        )
      ))}

      {/* agent 执行中的实时块：步骤时间线 + 流式正文；final 到达后由历史消息接管，不再重复展示。
          被用户中断时保留已收到的正文，但标题改成「已中断」，不再假装还在执行。 */}
      {agentRun && !agentRun.final && (
        <article className={`workspace-msg workspace-msg-assistant workspace-agent-live${agentRun.aborted ? ' is-aborted' : ''}`}>
          <span className="workspace-msg-mark" aria-hidden="true"><PetMark /></span>
          <div className="workspace-msg-body">
            <header className="workspace-msg-head">
              <strong>{personaName}</strong>
              <em>{agentRun.aborted ? '已中断' : 'Agent 执行中'}</em>
            </header>
            {agentRun.aborted ? (
              <p className="workspace-agent-aborted-note">这次回答已停止，下面是已收到的部分；可以直接继续提问。</p>
            ) : null}
            <AgentSteps steps={agentRun.steps} />
            <AgentThinking thinking={agentRun.thinking} live={!agentRun.final && !agentRun.aborted} />
            {agentRun.notice ? <p className="workspace-agent-notice">{agentRun.notice}</p> : null}
            {agentRun.streamingText ? (
              <div className="workspace-agent-streaming">
                <AssistantMessageMarkdown content={agentRun.streamingText} />
                {agentRun.aborted ? null : <span className="assistant-dock-cursor" aria-hidden="true" />}
              </div>
            ) : null}
          </div>
        </article>
      )}

      {extras}
    </div>
  )
}
