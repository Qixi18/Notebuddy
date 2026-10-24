import type { KeyboardEvent, RefObject } from 'react'

/** 输入区：Enter 发送（IME 组合中不触发）、Shift+Enter 换行；回答进行中时发送键变「停止」 */
export function AssistantComposer({ draft, onDraftChange, onSubmit, busy, onStop, placeholder, hint, scopeLabel, onScopeClick, onTermClick, onComposerFocus, textareaRef }: {
  draft: string
  onDraftChange: (draft: string) => void
  /** 返回 false 表示未发出（ busy / 空文本），调用方不清空草稿 */
  onSubmit: (text: string) => boolean
  busy: boolean
  /** 中断正在进行的回答；不传则不显示停止入口 */
  onStop?: () => void
  placeholder: string
  hint: string
  scopeLabel: string
  onScopeClick: () => void
  onTermClick: () => void
  onComposerFocus: () => void
  textareaRef?: RefObject<HTMLTextAreaElement | null>
}) {
  function submit() {
    const text = draft.trim()
    if (!text || busy) return
    if (onSubmit(text)) onDraftChange('')
  }

  function handleSubmit(event: KeyboardEvent<HTMLTextAreaElement> | { preventDefault: () => void }) {
    event.preventDefault()
    submit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    /* 回答进行中：Esc 直接中断，不用去点按钮 */
    if (event.key === 'Escape') {
      if (!busy || !onStop) return
      event.preventDefault()
      onStop()
      return
    }
    if (event.key !== 'Enter' || event.shiftKey) return
    /* 中文输入法选词的 Enter 不发送 */
    if (event.nativeEvent.isComposing) return
    event.preventDefault()
    submit()
  }

  return (
    <form
      className="workspace-composer"
      onSubmit={handleSubmit}
    >
      <textarea
        ref={textareaRef}
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={onComposerFocus}
        placeholder={placeholder}
        rows={2}
        aria-label="课程问题"
      />
      <div className="workspace-composer-foot">
        <div className="workspace-composer-tools">
          <button type="button" className="workspace-composer-tool" onClick={onTermClick}>术语</button>
          <button type="button" className="workspace-composer-tool" onClick={onScopeClick} title="修改提问范围">
            {scopeLabel}
          </button>
        </div>
        <span className="workspace-composer-hint">{hint}</span>
        {busy && onStop ? (
          <button className="primary-button workspace-composer-stop" type="button" onClick={onStop}>
            停止 <span aria-hidden="true">■</span>
          </button>
        ) : (
          <button className="primary-button" type="submit" disabled={!draft.trim() || busy}>
            {busy ? '正在翻资料…' : '发送'} <span aria-hidden="true">↑</span>
          </button>
        )}
      </div>
    </form>
  )
}
