import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../api'
import { AssistantComposer } from '../assistant/AssistantComposer'
import { AssistantThread } from '../assistant/AssistantThread'
import { useConversation } from '../conversation/useConversation'
import { teacherPersonaMeta } from '../persona/personas'

export type NotebookScopeTarget = { id: string; title: string }

/**
 * 独立答疑页的 Notebook 范围面板。
 *
 * 为什么单独一个组件：Notebook 会话必须由 ``/notebooks/{id}/conversations`` 建立
 * （后端约束 ``scope='notebook' => course_id IS NULL``），而 ``useConversation`` 的
 * 课程/Notebook 绑定是 hook 级参数。这里用第二个 hook 实例挂到选中的 Notebook 上，
 * 复用同一套会话、SSE 与核验后发布链路，不复活旧 Note 会话，也不用伪 courseId。
 */
export function NotebookScopePanel({ courseId, notebook, onExit }: {
  courseId: string
  notebook: NotebookScopeTarget
  /** 退出 Notebook 范围，回到整门课程范围 */
  onExit: () => void
}) {
  const conversation = useConversation(undefined, notebook.id)
  const { askAgent, stopAgent, ready, busy, messages, agentRun } = conversation
  const persona = teacherPersonaMeta()
  const [draft, setDraft] = useState('')
  const [revision, setRevision] = useState<number | null>(null)
  const [error, setError] = useState<string>()
  const composerRef = useRef<HTMLTextAreaElement>(null)

  /* 提问必须绑定「已保存正文」的 revision：本地未保存草稿不算事实来源（澄清见路线图 §2.4） */
  useEffect(() => {
    let active = true
    setRevision(null)
    void api.getNotebookDocument(courseId, notebook.id)
      .then((document) => { if (active) setRevision(document.revision) })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Notebook 正文读取失败')
      })
    return () => { active = false }
  }, [courseId, notebook.id])

  const send = useCallback((text: string): boolean => {
    const question = text.trim()
    if (!question || busy) return false
    if (revision === null) {
      setError('正在读取 Notebook 正文版本，请稍候再提问')
      return false
    }
    setError(undefined)
    void askAgent(question, {
      scope: 'notebook',
      notebookContext: {
        course_id: courseId,
        notebook_id: notebook.id,
        revision,
        title: notebook.title.slice(0, 200),
      },
    }).then((sent) => { if (!sent) setDraft(question) })
    return true
  }, [askAgent, busy, courseId, notebook.id, notebook.title, revision])

  const starters = useMemo(() => [
    `这本《${notebook.title}》最重要的三个概念是什么？`,
    '把当前正文的核心结论整理成要点。',
    '正文里哪些地方缺少原始资料支持？',
  ], [notebook.title])

  const handleFeedback = useCallback(async (messageId: string, category: 'helpful' | 'not_helpful', comment?: string) => {
    try {
      await api.saveFeedback(courseId, { target_type: 'assistant_message', target_id: messageId, category, comment })
      return true
    } catch {
      return false
    }
  }, [courseId])

  return (
    <>
      <div className="workspace-context" aria-label="Notebook 提问上下文">
        <span className="workspace-chip workspace-scope">
          <span>范围</span>
          <strong>Notebook《{notebook.title}》</strong>
        </span>
        <span className="workspace-context-summary">
          先读已保存正文（revision {revision ?? '读取中'}），再用该 Notebook 的原始资料核验；核验完成前不显示草稿。
        </span>
        <button type="button" className="text-button" onClick={onExit}>切回整门课程</button>
      </div>

      {error ? <p className="workspace-error" role="alert">{error}</p> : null}

      <AssistantThread
        ready={ready}
        busy={busy}
        messages={messages}
        conversationId={conversation.conversationId}
        personaName={persona.name}
        starters={starters}
        onStarter={(prompt) => { setDraft(prompt); composerRef.current?.focus() }}
        onFeedback={handleFeedback}
        onRetry={send}
        onFollowUp={(prompt) => { setDraft(prompt); composerRef.current?.focus() }}
        agentRun={agentRun}
        suggestionsByMessage={conversation.agentSuggestionsByMessage}
        highlightMessageId={conversation.pendingMessageId}
        onHighlightConsumed={conversation.consumePendingMessage}
        extras={(
          <p className="workspace-inline-status" role="status">
            本范围只读这本 Notebook：不会检索课程其他资料，也不会修改正文。
          </p>
        )}
      />

      <div className="workspace-chat-foot">
        <AssistantComposer
          draft={draft}
          onDraftChange={setDraft}
          onSubmit={send}
          busy={busy}
          onStop={() => stopAgent()}
          placeholder={`问这本《${notebook.title}》的问题……`}
          hint="Enter 发送 · Shift+Enter 换行 · 回答经过证据核验后才显示"
          scopeLabel={`Notebook《${notebook.title}》`}
          onScopeClick={onExit}
          onTermClick={() => undefined}
          onComposerFocus={() => undefined}
          textareaRef={composerRef}
          quickPrompts={[]}
          onQuickPrompt={(prompt) => { setDraft(prompt); composerRef.current?.focus() }}
        />
      </div>
    </>
  )
}
