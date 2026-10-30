import { request } from './http'
import type { SettingsStatus, SettingsUpdateResponse } from '../types'

export type ProviderStatus = { provider: string; configured: boolean; status: string; checked_at: string | null; message?: string | null }
export type ConnectivityTestPayload = {
  provider: 'deepseek' | 'embedding'
  api_key?: string
  base_url?: string
  model?: string
}
export type OCRStatus = { enabled: boolean; available: boolean; status: string; provider: string; max_pages: number; language: string; timeout_seconds: number }
export type ProcessingRoute = 'standard' | 'llm'
export type Capabilities = { allowed_extensions: string[]; max_upload_bytes: number; max_pages: number; ocr: OCRStatus; default_processing_route?: ProcessingRoute; processing_routes?: Record<ProcessingRoute, { max_upload_bytes: number; max_pages: number }> }

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
  testConnectivity: (payload: ConnectivityTestPayload) =>
    request<ProviderStatus>('/api/v1/config/test-connectivity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  getCapabilities: () => request<Capabilities>('/api/v1/config/capabilities'),
}
