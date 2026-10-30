import type { Job, Material } from '../types'

export function ProcessingStatus({ job, material }: { job?: Job; material?: Material }) {
  const status = job?.status ?? material?.status
  if (!status) return null
  const failed = status === 'failed'
  const completed = status === 'completed'
  const progress = completed ? 100 : Math.max(0, Math.min(100, job?.progress ?? 0))
  const phase = job?.phase
  const format = material?.original_filename.split('.').pop()?.toUpperCase() || '课件'
  const ai = material?.processing_route === 'llm'
  const stage = ai ? failed ? 'AI 读取未完成' : completed ? 'AI 读取完成' : phase === 'ai_read' ? `AI 读取页面 · ${job?.completed_pages ?? 0} / ${job?.total_pages ?? material?.page_count ?? 0}` : '准备 AI 读取' : status === 'pending' ? '等待课件解析' : status === 'failed' ? '课件解析未完成' : completed ? '资料解析完成' : phase === 'web_search' ? '检索课程相关网络资料' : phase === 'knowledge' || progress >= 96 && progress < 98 ? '整理课程知识点与笔记' : phase === 'index' || progress >= 98 ? '建立本地课程检索索引' : progress < 10 ? `准备读取 ${format}` : '解析课件位置'

  return (
    <section className={`processing-card processing-${status}`} aria-live="polite" aria-atomic="true">
      <div className="processing-card-heading">
        <span className={`processing-status-mark processing-status-${status}`} aria-hidden="true">{completed ? '✓' : failed ? '!' : '·'}</span>
        <strong>{stage}</strong>
        {!failed && <span className="processing-percent">{progress}%</span>}
      </div>
      {!failed && <div className="progress-track" role="progressbar" aria-label="课件解析进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>}
      <p>{failed ? job?.error_message || '读取未完成，可重试继续。' : ai ? '已完成页面会保存进度；读取完成后继续组织笔记、更新知识树并分析知识联系。' : completed ? `${material?.page_count ?? 0} 个位置已解析，后续生成状态见笔记页面。` : '本地解析完成后继续生成笔记。'}</p>
    </section>
  )
}
