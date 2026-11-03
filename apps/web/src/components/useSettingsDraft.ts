import { useEffect, useState } from 'react'

import { api } from '../api'
import type { ProviderStatus } from '../api'
import type { SettingsStatus } from '../types'
import type { VisionCapabilityStatus } from '../api/config'
import { readSidebarQuote, saveSidebarQuote } from '../features/navigation/sidebarQuote'

type Draft = {
  NOTEBOOK_DOCUMENT_PROCESSING_ROUTE: string
  DEEPSEEK_BASE_URL: string
  DEEPSEEK_MODEL: string
  DEEPSEEK_TIMEOUT_SECONDS: string
  NOTEBOOK_MAX_UPLOAD_MB: string
  EMBEDDING_BASE_URL: string
  EMBEDDING_MODEL: string
  NOTEBOOK_VISION_BASE_URL: string
  NOTEBOOK_VISION_MODEL: string
  NOTEBOOK_VISION_TIMEOUT_SECONDS: string
  DEEPSEEK_INPUT_COST_PER_MILLION: string
  DEEPSEEK_OUTPUT_COST_PER_MILLION: string
  DEEPSEEK_PRICE_VERSION: string
  DEEPSEEK_PRICE_SOURCE: string
  NOTEBOOK_VISION_INPUT_COST_PER_MILLION: string
  NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION: string
  NOTEBOOK_VISION_MAX_IMAGE_TOKENS: string
  NOTEBOOK_VISION_PRICE_VERSION: string
  NOTEBOOK_VISION_PRICE_SOURCE: string
  NOTEBOOK_BUDGET_USD_CNY_RATE: string
  NOTEBOOK_BUDGET_FX_RATE_SOURCE: string
  NOTEBOOK_BUDGET_FX_RATE_AS_OF: string
  NOTEBOOK_BUDGET_FX_BUFFER_PERCENT: string
}

/** 密钥草稿：留空表示"不修改"，只有真正输入了新值才会提交。 */
type SecretDraft = {
  DEEPSEEK_API_KEY: string
  EMBEDDING_API_KEY: string
  NOTEBOOK_VISION_API_KEY: string
}

const EMPTY_SECRETS: SecretDraft = { DEEPSEEK_API_KEY: '', EMBEDDING_API_KEY: '', NOTEBOOK_VISION_API_KEY: '' }

type ConnectiveProvider = 'deepseek' | 'embedding' | 'vision'

function buildDraft(status: SettingsStatus): Draft {
  return {
    NOTEBOOK_DOCUMENT_PROCESSING_ROUTE: status.storage.processing_route ?? 'standard',
    DEEPSEEK_BASE_URL: status.deepseek.base_url ?? '',
    DEEPSEEK_MODEL: status.deepseek.model ?? '',
    DEEPSEEK_TIMEOUT_SECONDS: String(status.deepseek.timeout_seconds ?? ''),
    NOTEBOOK_MAX_UPLOAD_MB: String(status.storage.max_upload_mb ?? ''),
    EMBEDDING_BASE_URL: status.embedding.base_url ?? '',
    EMBEDDING_MODEL: status.embedding.model ?? '',
    NOTEBOOK_VISION_BASE_URL: status.vision.base_url ?? '',
    NOTEBOOK_VISION_MODEL: status.vision.model ?? '',
    NOTEBOOK_VISION_TIMEOUT_SECONDS: String(status.vision.timeout_seconds ?? '60'),
    DEEPSEEK_INPUT_COST_PER_MILLION: String(status.budget?.text?.input_usd_per_million ?? ''),
    DEEPSEEK_OUTPUT_COST_PER_MILLION: String(status.budget?.text?.output_usd_per_million ?? ''),
    DEEPSEEK_PRICE_VERSION: String(status.budget?.text?.tariff_version ?? ''),
    DEEPSEEK_PRICE_SOURCE: String(status.budget?.text?.price_source ?? ''),
    NOTEBOOK_VISION_INPUT_COST_PER_MILLION: String(status.budget?.vision?.input_usd_per_million ?? ''),
    NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION: String(status.budget?.vision?.output_usd_per_million ?? ''),
    NOTEBOOK_VISION_MAX_IMAGE_TOKENS: String(status.budget?.vision?.max_image_tokens ?? ''),
    NOTEBOOK_VISION_PRICE_VERSION: String(status.budget?.vision?.tariff_version ?? ''),
    NOTEBOOK_VISION_PRICE_SOURCE: String(status.budget?.vision?.price_source ?? ''),
    NOTEBOOK_BUDGET_USD_CNY_RATE: String(status.budget?.fx_usd_cny ?? ''),
    NOTEBOOK_BUDGET_FX_RATE_SOURCE: String(status.budget?.fx_source ?? ''),
    NOTEBOOK_BUDGET_FX_RATE_AS_OF: String(status.budget?.fx_as_of ?? ''),
    NOTEBOOK_BUDGET_FX_BUFFER_PERCENT: String(status.budget?.fx_buffer_percent ?? '25'),
  }
}

export function useSettingsDraft() {
  const [status, setStatus] = useState<SettingsStatus>()
  const [draft, setDraft] = useState<Draft>()
  const [original, setOriginal] = useState<Draft>()
  const [secrets, setSecrets] = useState<SecretDraft>(EMPTY_SECRETS)
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<ConnectiveProvider | null>(null)
  const [testResults, setTestResults] = useState<Partial<Record<ConnectiveProvider, ProviderStatus>>>({})
  const [visionPreflightResult, setVisionPreflightResult] = useState<VisionCapabilityStatus>()
  const [error, setError] = useState<string>()
  const [notice, setNotice] = useState<string>()
  const [sidebarQuote, setSidebarQuote] = useState(readSidebarQuote)
  const [originalSidebarQuote, setOriginalSidebarQuote] = useState(sidebarQuote)

  useEffect(() => {
    void load()
  }, [])

  async function load() {
    try {
      setLoading(true)
      setError(undefined)
      const next = await api.getSettings()
      setStatus(next)
      const nextDraft = buildDraft(next)
      setDraft(nextDraft)
      setOriginal(nextDraft)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '设置读取失败')
    } finally {
      setLoading(false)
    }
  }

  const dirty =
    draft && original
      ? (Object.keys(draft) as (keyof Draft)[]).filter((key) => draft[key] !== original[key])
      : []

  const secretTouched = (Object.keys(secrets) as (keyof SecretDraft)[]).filter(
    (key) => secrets[key].trim().length > 0,
  )

  /** 密钥写入：默认本地开放；仅当后端配置了口令时才要求填入口令。 */
  const secretWriteReady =
    status?.limits.secret_write_enabled &&
    (status.limits.token_required ? token.trim().length > 0 : true)

  const quoteChanged = sidebarQuote !== originalSidebarQuote
  const changeCount = dirty.length + secretTouched.length + Number(quoteChanged)

  async function handleSave() {
    if (changeCount === 0) return
    if (secretTouched.length > 0 && !secretWriteReady) {
      setError(
        status?.limits.secret_write_enabled
          ? '后端已开启口令校验：请先在下方填入口令，再保存密钥。'
          : '密钥写入未开启：需在 .env 中设置 NOTEBOOK_ALLOW_SECRET_WRITE=true 后重启后端。',
      )
      return
    }

    const updates: Record<string, string> = {}
    for (const key of dirty) updates[key] = draft![key]
    for (const key of secretTouched) updates[key] = secrets[key].trim()

    try {
      setSaving(true)
      setError(undefined)
      setNotice(undefined)
      let savedCount = 0
      let backup = ''
      let warn = ''
      if (Object.keys(updates).length > 0) {
        const response = await api.updateSettings(updates, token || undefined)
        setStatus(response.status)
        const nextDraft = buildDraft(response.status)
        setDraft(nextDraft)
        setOriginal(nextDraft)
        setSecrets(EMPTY_SECRETS)
        setToken('')
        savedCount = response.updated.length
        backup = response.backup_path ? `，原配置已备份至 ${response.backup_path}` : ''
        warn = response.warnings.length > 0 ? `　⚠ ${response.warnings.join('；')}` : ''
      }
      if (quoteChanged) {
        const savedQuote = saveSidebarQuote(sidebarQuote)
        setSidebarQuote(savedQuote)
        setOriginalSidebarQuote(savedQuote)
        savedCount += 1
      }
      window.dispatchEvent(new Event('notebuddy-settings-changed'))
      setNotice(`已保存 ${savedCount} 项配置${backup}${warn}`)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '设置保存失败'
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  function update(key: keyof Draft, value: string) {
    setDraft((current) => (current ? { ...current, [key]: value } : current))
  }

  function updateSecret(key: keyof SecretDraft, value: string) {
    setSecrets((current) => ({ ...current, [key]: value }))
  }

  /** 点击"测试连接"：用当前表单草稿值单选测一个 API（不落盘、互不影响）。 */
  async function handleTest(provider: ConnectiveProvider) {
    if (provider === 'vision') {
      await handleVisionPreflight()
      return
    }
    try {
      setTesting(provider)
      setError(undefined)
      setNotice(undefined)
      const isDeepseek = provider === 'deepseek'
      const result = await api.testConnectivity(
        isDeepseek
          ? {
              provider,
              api_key: secrets.DEEPSEEK_API_KEY.trim() || undefined,
              base_url: draft?.DEEPSEEK_BASE_URL,
              model: draft?.DEEPSEEK_MODEL,
            }
          : {
              provider,
              api_key: secrets.EMBEDDING_API_KEY.trim() || undefined,
              base_url: draft?.EMBEDDING_BASE_URL,
              model: draft?.EMBEDDING_MODEL,
            },
      )
      setTestResults((current) => ({ ...current, [provider]: result }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '连接测试失败')
    } finally {
      setTesting(null)
    }
  }

  async function handleVisionPreflight() {
    try {
      setTesting('vision')
      setError(undefined)
      setNotice(undefined)
      const result = await api.testVisionCapability({
        base_url: draft?.NOTEBOOK_VISION_BASE_URL,
        model: draft?.NOTEBOOK_VISION_MODEL,
        timeout_seconds: Number(draft?.NOTEBOOK_VISION_TIMEOUT_SECONDS || 60),
        api_key: secrets.NOTEBOOK_VISION_API_KEY.trim() || undefined,
      })
      setVisionPreflightResult(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '视觉模型图片预检失败')
    } finally {
      setTesting(null)
    }
  }

  return {
    status, draft, secrets, token, setToken, loading, saving, testing, testResults,
    visionPreflightResult,
    error, setError, notice, changeCount, secretTouched, secretWriteReady,
    handleSave, handleTest, handleVisionPreflight, update, updateSecret,
    sidebarQuote, setSidebarQuote,
  }
}
