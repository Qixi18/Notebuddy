import { request } from './http'
import type { SettingsStatus, SettingsUpdateResponse } from '../types'

export type ProviderStatus = { provider: string; configured: boolean; status: string; checked_at: string | null; message?: string | null }
export type ConnectivityTestPayload = {
  provider: 'deepseek' | 'embedding'
  api_key?: string
  base_url?: string
  model?: string
}
export type ProviderCall = { id: string; provider: string; operation: string; status: string; course_id: string | null; material_id: string | null; model: string | null; request_units: number | null; response_units: number | null; estimated_cost_usd: number | null; duration_ms: number | null; error_type: string | null; metadata_json: string; started_at: string; completed_at: string | null; created_at: string }
export type OCRStatus = { enabled: boolean; available: boolean; status: string; provider: string; max_pages: number; language: string; timeout_seconds: number }
export type Capabilities = { allowed_extensions: string[]; max_upload_bytes: number; max_pages: number; ocr: OCRStatus }

export const configApi = {
  getSettings: () => request<SettingsStatus>('/api/v1/settings'),
  updateSettings: (updates: Record<string, string>, token?: string) =>
    request<SettingsUpdateResponse>('/api/v1/settings', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'X-Notebook-Settings-Token': token } : {}),
      },
      body: JSON.stringify(updates),
    }),
  getWebSearchStatus: () => request<{ configured: boolean; provider: string; status: string }>('/api/v1/web-search/status'),
  getConfigStatus: () => request<Record<string, ProviderStatus>>('/api/v1/config/status'),
  checkProvider: (provider: 'deepseek' | 'embedding' | 'tavily') => request<ProviderStatus>(`/api/v1/config/check/${provider}`, { method: 'POST' }),
  testConnectivity: (payload: ConnectivityTestPayload) =>
    request<ProviderStatus>('/api/v1/config/test-connectivity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  getDiagnostics: () => request<Record<string, unknown>>('/api/v1/config/diagnostics'),
  listProviderCalls: (limit = 50) => request<ProviderCall[]>(`/api/v1/config/provider-calls?limit=${limit}`),
  getCapabilities: () => request<Capabilities>('/api/v1/config/capabilities'),
  getOCRStatus: () => request<OCRStatus>('/api/v1/ocr/status'),
}
