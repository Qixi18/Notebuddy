import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Capabilities, ProcessingRoute } from '../../api/config'

export function useProcessingRoute() {
  const [route, setRoute] = useState<ProcessingRoute>()
  const [capabilities, setCapabilities] = useState<Capabilities>()
  useEffect(() => {
    let active = true
    const load = () => {
      void api.getCapabilities?.()?.then(value => {
        if (active && value) { setCapabilities(value); setRoute(value.default_processing_route ?? 'standard') }
      }).catch(() => { /* The server resolves its saved default when no override is provided. */ })
    }
    load()
    window.addEventListener('notebuddy-settings-changed', load)
    return () => { active = false; window.removeEventListener('notebuddy-settings-changed', load) }
  }, [])
  return { route, setRoute, capabilities }
}

export function ProcessingRouteControl({ value, onChange, disabled = false, purpose = 'notebook' }: {
  value?: ProcessingRoute; onChange: (value: ProcessingRoute) => void; disabled?: boolean
  purpose?: 'notebook' | 'curriculum'
}) {
  return <label className="processing-route-control">本次处理路线
    <select aria-label="本次文档处理路线" value={value ?? ''} disabled={disabled}
      onChange={event => onChange(event.target.value as ProcessingRoute)}>
      {!value && <option value="">使用设置中的默认路线</option>}
      <option value="standard">标准处理</option><option value="llm">{purpose === 'curriculum' ? '全程 AI' : 'AI 增强'}</option>
    </select>
    <small>{value === 'llm' ? (purpose === 'curriculum' ? '通过模型逐页读取课程表，分批提取课程；按页使用 API。' : '优先本地解析，疑难页由视觉 AI 读取，再由 AI 整理笔记；成功步骤可续用。') : '可在设置中更改新上传的默认路线。'}</small>
  </label>
}
