import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react'

/**
 * 输入区（WorkBuddy 式能力行，v6 用户反馈）：
 * - 输入框上方一行「能力 chips」：任务类（考考我/复习提纲/易混概念，点击只填草稿）
 *   与模式类（直接答/引导我、课件收窄、术语）——功能可发现，不必靠用户记住话术；
 * - Enter 发送（IME 组合中不触发）、Shift+Enter 换行；回答进行中时发送键变「停止」；
 * - 课件收窄（P3）仅「整门课程」档由页面传入 materials 时显示——消息级参数，
 *   收窄不写会话 scope、不触发锁定，切档/切会话由页面负责复位。
 */
export function AssistantComposer({ draft, onDraftChange, onSubmit, busy, onStop, placeholder, hint, scopeLabel, onScopeClick, onTermClick, onComposerFocus, textareaRef, materials, materialId, onMaterialChange, learningMode, onLearningModeChange, quickPrompts, onQuickPrompt }: {
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
  /** 当前课程可选课件；不传（非 course 档 / 无课件）就不显示收窄控件 */
  materials?: Array<{ id: string; lecture_title: string }>
  /** 已选中的收窄课件；undefined = 全部课件 */
  materialId?: string
  onMaterialChange?: (materialId?: string) => void
  /** 学习模式（P9）：direct=直接答 / guided=引导式；chip 点击切换 */
  learningMode?: 'direct' | 'guided'
  onLearningModeChange?: (mode: 'direct' | 'guided') => void
  /** 任务类能力 chips：点击把 prompt 填进输入框，由用户决定发送 */
  quickPrompts?: Array<{ label: string; prompt: string }>
  onQuickPrompt?: (prompt: string) => void
}) {
  const [materialMenuOpen, setMaterialMenuOpen] = useState(false)
  const materialRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!materialMenuOpen) return
    function onDocClick(event: MouseEvent) {
      if (materialRef.current && !materialRef.current.contains(event.target as Node)) setMaterialMenuOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [materialMenuOpen])

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

  const pickedMaterial = materials?.find((item) => item.id === materialId)
  const showMaterialPicker = Boolean(materials?.length && onMaterialChange)
  const showQuickRow = Boolean((quickPrompts?.length && onQuickPrompt) || onLearningModeChange || showMaterialPicker || onTermClick)

  return (
    <form
      className="workspace-composer"
      onSubmit={handleSubmit}
    >
      {showQuickRow && (
        <div className="workspace-quick-actions">
          {onQuickPrompt && quickPrompts?.map((item) => (
            <button
              key={item.label}
              type="button"
              className="workspace-quick-chip"
              title={`填入：${item.prompt}`}
              onClick={() => onQuickPrompt(item.prompt)}
            >{item.label}</button>
          ))}
          <span className="workspace-quick-spacer" aria-hidden="true" />
          {onLearningModeChange && (
            <button
              type="button"
              className={`workspace-quick-chip is-mode${learningMode === 'guided' ? ' is-active' : ''}`}
              onClick={() => onLearningModeChange(learningMode === 'guided' ? 'direct' : 'guided')}
              title={learningMode === 'guided'
                ? '引导模式已开：AI 会先诊断卡点、分步给提示；点击切回直接答'
                : '切换到引导模式：AI 先诊断卡点、分步给提示，不直接给答案'}
              aria-pressed={learningMode === 'guided'}
            >
              {learningMode === 'guided' ? '引导我' : '直接答'}
            </button>
          )}
          {showMaterialPicker && (
            <div className="workspace-material-wrap" ref={materialRef}>
              <button
                type="button"
                className={`workspace-quick-chip is-mode${materialId ? ' is-active' : ''}`}
                onClick={() => setMaterialMenuOpen((open) => !open)}
                title="只检索某一讲课件（仅影响本轮回答，不改变范围）"
                aria-haspopup="true"
                aria-expanded={materialMenuOpen}
              >
                课件 · <span className="workspace-material-label">{pickedMaterial ? pickedMaterial.lecture_title : '全部'}</span>
              </button>
              {materialMenuOpen && (
                <div className="workspace-material-menu" role="menu" aria-label="选择收窄课件">
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={!materialId}
                    className={`workspace-scope-option${materialId ? '' : ' is-active'}`}
                    onClick={() => { onMaterialChange?.(undefined); setMaterialMenuOpen(false) }}
                  >全部课件</button>
                  {materials!.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="menuitemradio"
                      aria-checked={materialId === item.id}
                      className={`workspace-scope-option${materialId === item.id ? ' is-active' : ''}`}
                      title={item.lecture_title}
                      onClick={() => { onMaterialChange?.(item.id); setMaterialMenuOpen(false) }}
                    >{item.lecture_title}</button>
                  ))}
                </div>
              )}
            </div>
          )}
          <button type="button" className="workspace-quick-chip is-mode" onClick={onTermClick} title="解释一个术语的课件出处">术语</button>
        </div>
      )}
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
        <button type="button" className="workspace-composer-tool" onClick={onScopeClick} title="修改提问范围">
          {scopeLabel}
        </button>
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
