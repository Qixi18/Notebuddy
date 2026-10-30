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

export function ProcessingRouteControl({ value, onChange, disabled = false }: {
  value?: ProcessingRoute; onChange: (value: ProcessingRoute) => void; disabled?: boolean
}) {
  return <label className="processing-route-control">本次处理路线
    <select aria-label="本次文档处理路线" value={value ?? ''} disabled={disabled}
      onChange={event => onChange(event.target.value as ProcessingRoute)}>
      {!value && <option value="">使用设置中的默认路线</option>}
      <option value="standard">标准处理</option><option value="llm">全程 AI</option>
    </select>
    <small>{value === 'llm' ? '通过模型读取页面并整理笔记，按页使用 API。' : '可在设置中更改新上传的默认路线。'}</small>
  </label>
}
