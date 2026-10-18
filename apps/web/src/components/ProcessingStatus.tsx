import type { Job, Material } from '../types'

export function ProcessingStatus({ job, material }: { job?: Job; material?: Material }) {
  const status = job?.status ?? material?.status
  if (!status) return null
  const failed = status === 'failed'
  const completed = status === 'completed'
  const progress = completed ? 100 : Math.max(0, Math.min(100, job?.progress ?? 0))
  const phase = job?.phase
  const format = material?.original_filename.split('.').pop()?.toUpperCase() || '课件'
  const stage = status === 'pending' ? '等待课件解析' : status === 'failed' ? '课件解析未完成' : completed ? '本地整理与索引完成' : phase === 'web_search' ? '检索课程相关网络资料' : phase === 'knowledge' || progress >= 96 && progress < 98 ? '整理课程知识点与笔记' : phase === 'index' || progress >= 98 ? '建立本地课程检索索引' : progress < 10 ? `准备读取 ${format}` : '解析课件位置'

  return (
    <section className={`processing-card processing-${status}`} aria-live="polite" aria-atomic="true">
      <div className="processing-card-heading">
        <span className={`processing-status-mark processing-status-${status}`} aria-hidden="true">{completed ? '✓' : failed ? '!' : '·'}</span>
        <strong>{stage}</strong>
        {!failed && <span className="processing-percent">{progress}%</span>}
      </div>
      {!failed && <div className="progress-track" role="progressbar" aria-label="课件解析进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>}
      <p>{failed ? job?.error_message || '解析过程中遇到问题。请确认文件可正常打开后重新上传。' : job?.web_search_status === 'unavailable' ? '联网检索未配置；本次仅执行本地课件解析、知识点整理和检索索引。' : job?.web_search_status === 'failed' ? '联网检索失败，但本地课件解析流程继续完成。可检查 Tavily 配置或网络后重试。' : job?.web_search_status === 'no_results' ? '联网检索未找到达到相关性阈值的来源；课程内容仍按课件解析结果整理。' : job?.web_search_status === 'completed' ? '已完成联网检索。外部来源会与原始课件引用分开显示。' : completed ? `${material?.page_count ?? 0} 个位置已解析，并已完成知识点整理与本地索引。` : '处理步骤包括课件解析、课程知识点整理、本地检索索引；已配置时还会单独执行联网搜索。'}</p>
    </section>
  )
}
