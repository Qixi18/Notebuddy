import { useEffect, useRef, useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'
import { Link } from 'react-router-dom'

import { useWorkspace } from './AppLayout'
import { TeacherCharacter } from './TeacherCharacter'
import { teacherPersonaMeta } from '../features/persona/personas'

/**
 * 悬浮答疑坞。与答疑页共用 useConversation 的同一份会话，
 * 因此这里问过的问题会落库，切到答疑页也能看到完整历史。
 */
export function AssistantDock() {
  const { course, courseId, courses, teacherPersona, conversation } = useWorkspace()
  const [draft, setDraft] = useState('')
  const recentMessages = conversation.messages.slice(-4)
  const fallbackCourse = courses[0]
  const persona = teacherPersonaMeta(teacherPersona)
  const messagesRef = useRef<HTMLDivElement>(null)
  const lastMessage = recentMessages[recentMessages.length - 1]
  /* 消息变化后重新定位视口：新回复很长时把它的开头对齐到顶部（读到的是正文开头），
     等待回复或最后一条是自己提问时落到最底部 */
  const bottomKey = `${recentMessages.length}:${lastMessage?.content.length ?? 0}:${conversation.busy}`

  useEffect(() => {
    const node = messagesRef.current
    if (!node) return
    const last = node.lastElementChild as HTMLElement | null
    if (last?.classList.contains('assistant-dock-message-assistant')) {
      node.scrollTop += Math.round(last.getBoundingClientRect().top - node.getBoundingClientRect().top) - 2
    } else {
      node.scrollTop = node.scrollHeight
    }
  }, [bottomKey])

  async function submitQuestion(event: FormEvent) {
    event.preventDefault()
    if (!courseId || !draft.trim() || conversation.busy) return
    const text = draft
    setDraft('')
    if (!await conversation.ask(text)) setDraft(text)
  }

  return (
    <aside className="assistant-dock" aria-label="课程学习助手">
      <header className="assistant-dock-heading">
        <span className="assistant-dock-mark" aria-hidden="true">✦</span>
        <div><strong>{persona.name} · 学习助手</strong><small>{course?.name ?? '选择课程后开始提问'}</small></div>
      </header>
      {/* 侧边答疑坞展示完整立绘：不用 compact（那是 48px 头像的尺寸语义），
          animated 让它与首页一致走连续帧雪碧图，而不是静态立绘 */}
      <div className="assistant-dock-teacher"><TeacherCharacter animated status={conversation.busy ? 'thinking' : 'idle'} character={teacherPersona} /></div>
      {courseId ? (
        <>
          <div className="assistant-dock-intro"><strong>随时问一问</strong><small>优先从课程资料中查找，并标出出处。</small></div>
          <div className="assistant-dock-messages" aria-live="polite" ref={messagesRef}>
            {recentMessages.map((message, index) => (
              <article className={`assistant-dock-message assistant-dock-message-${message.role}`} key={`${message.role}-${index}-${message.content.slice(0, 12)}`}>
                <small>{message.role === 'user' ? '你' : persona.name}</small>
                {/* 老师回答走与答疑页同一条 Markdown 管线（remark-math + rehype-katex），
                    否则 ### / ** / 列表会以原始标记直接显示出来；自己的提问保持纯文本 */}
                {message.role === 'assistant'
                  ? <div className="assistant-dock-answer"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{message.content}</ReactMarkdown></div>
                  : <p>{message.content}</p>}
                {message.role === 'assistant' && message.sources?.length ? <span>{message.sources.length} 条资料来源</span> : null}
              </article>
            ))}
          </div>
          <form className="assistant-dock-form" onSubmit={submitQuestion}>
            <textarea aria-label="快速提问" placeholder="问问当前课程…" value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} />
            <div><Link to={`/courses/${courseId}/assistant`}>打开完整答疑</Link><button type="submit" disabled={!draft.trim() || conversation.busy}>{conversation.busy ? '思考中…' : '发送问题'}</button></div>
          </form>
        </>
      ) : fallbackCourse ? (
        <div className="assistant-dock-empty"><p>笔记书架展示全部课程内容。进入一门课程后，可以在这里继续提问。</p><Link className="text-button" to={`/courses/${fallbackCourse.id}/assistant`}>打开课程答疑</Link></div>
      ) : <div className="assistant-dock-empty"><p>创建课程并上传学习资料后，可以使用课程答疑。</p><Link className="text-button" to="/">创建课程</Link></div>}
    </aside>
  )
}
