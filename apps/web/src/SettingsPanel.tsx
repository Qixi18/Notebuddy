import { useEffect, useState } from 'react'

import { api } from './api'
import type { ProviderStatus } from './api'
import type { SettingsStatus } from './types'

type SettingsPanelProps = {
  onClose: () => void
}

type Draft = {
  DEEPSEEK_BASE_URL: string
  DEEPSEEK_MODEL: string
  DEEPSEEK_TIMEOUT_SECONDS: string
  NOTEBOOK_MAX_UPLOAD_MB: string
  EMBEDDING_BASE_URL: string
  EMBEDDING_MODEL: string
}

/** 密钥草稿：留空表示"不修改"，只有真正输入了新值才会提交。 */
type SecretDraft = {
  DEEPSEEK_API_KEY: string
  EMBEDDING_API_KEY: string
}

const EMPTY_SECRETS: SecretDraft = { DEEPSEEK_API_KEY: '', EMBEDDING_API_KEY: '' }

type ConnectiveProvider = 'deepseek' | 'embedding'

function connectionLabel(status: string | undefined): string {
  switch (status) {
    case 'connected': return '连接成功'
    case 'authentication_failed': return '认证失败（Key 无效）'
    case 'rate_limited': return '触发限流，请稍后再试'
    case 'timeout': return '连接超时'
    case 'unavailable': return '服务不可达'
    case 'configured_untested': return '已保存，尚未验证'
    case 'unconfigured': return '未配置 Key，无法测试'
    default: return status ?? '未知状态'
  }
}

function isFailure(status: string | undefined): boolean {
  return status === 'authentication_failed' || status === 'rate_limited'
    || status === 'timeout' || status === 'unavailable'
}

function buildDraft(status: SettingsStatus): Draft {
  return {
    DEEPSEEK_BASE_URL: status.deepseek.base_url ?? '',
    DEEPSEEK_MODEL: status.deepseek.model ?? '',
    DEEPSEEK_TIMEOUT_SECONDS: String(status.deepseek.timeout_seconds ?? ''),
    NOTEBOOK_MAX_UPLOAD_MB: String(status.storage.max_upload_mb ?? ''),
    EMBEDDING_BASE_URL: status.embedding.base_url ?? '',
    EMBEDDING_MODEL: status.embedding.model ?? '',
  }
}

/** 设置面板：展示脱敏状态 + 写入白名单内的安全配置项。 */
export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [status, setStatus] = useState<SettingsStatus>()
  const [draft, setDraft] = useState<Draft>()
  const [original, setOriginal] = useState<Draft>()
  const [secrets, setSecrets] = useState<SecretDraft>(EMPTY_SECRETS)
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<ConnectiveProvider | null>(null)
  const [testResults, setTestResults] = useState<Partial<Record<ConnectiveProvider, ProviderStatus>>>({})
  const [error, setError] = useState<string>()
  const [notice, setNotice] = useState<string>()

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

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

  const changeCount = dirty.length + secretTouched.length

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
      const response = await api.updateSettings(updates, token || undefined)
      setStatus(response.status)
      const nextDraft = buildDraft(response.status)
      setDraft(nextDraft)
      setOriginal(nextDraft)
      setSecrets(EMPTY_SECRETS)
      setToken('')
      const backup = response.backup_path ? `，原配置已备份至 ${response.backup_path}` : ''
      const warn = response.warnings.length > 0 ? `　⚠ ${response.warnings.join('；')}` : ''
      setNotice(`已保存 ${response.updated.length} 项配置${backup}${warn}`)
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

  return (
    <div className="settings-backdrop" onClick={onClose} role="presentation">
      <aside
        className="settings-panel"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="设置"
      >
        <header className="settings-header">
          <div>
            <span className="eyebrow">SETTINGS</span>
            <h3>本地配置</h3>
          </div>
          <button className="settings-close" onClick={onClose} aria-label="关闭设置">×</button>
        </header>

        <div className="settings-body">
          {loading && <div className="muted-block">正在读取配置…</div>}

          {error && (
            <div className="alert settings-alert" role="alert">
              <span>{error}</span>
              <button onClick={() => setError(undefined)}>关闭</button>
            </div>
          )}
          {notice && <div className="settings-notice">{notice}</div>}

          {status && draft && (
            <>
              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>能力状态</span>
                  <small>密钥仅显示掩码</small>
                </div>
                <div className="status-grid">
                  <div className={`status-card ${status.deepseek.configured ? 'status-on' : 'status-off'}`}>
                    <div className="status-card-top">
                      <strong>DeepSeek</strong>
                      <span className="status-pill">{status.deepseek.configured ? '已启用' : '未配置'}</span>
                    </div>
                    <small>{status.deepseek.configured ? `Key ${status.deepseek.masked_key}` : '当前走本地规则降级'}</small>
                  </div>
                  <div className={`status-card ${status.embedding.configured ? 'status-on' : 'status-off'}`}>
                    <div className="status-card-top">
                      <strong>Embedding</strong>
                      <span className="status-pill">{status.embedding.configured ? '已启用' : '未配置'}</span>
                    </div>
                    <small>{status.embedding.configured ? `Key ${status.embedding.masked_key}` : '当前仅关键词检索'}</small>
                  </div>
                  <div className={`status-card ${status.limits.secret_write_enabled ? 'status-on' : 'status-off'}`}>
                    <div className="status-card-top">
                      <strong>密钥写入</strong>
                      <span className="status-pill">
                        {status.limits.secret_write_enabled ? '已开启' : '已关闭'}
                      </span>
                    </div>
                    <small>
                      {status.limits.secret_write_enabled
                        ? status.limits.token_required
                          ? '填入口令后可写入 API Key'
                          : '可直接在页面写入 DeepSeek / Embedding Key'
                        : '需在 .env 中开启开关'}
                    </small>
                  </div>
                </div>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>模型服务</span>
                  <small>写入 .env 并立即生效</small>
                </div>
                <label className="field">
                  <span>DeepSeek 服务地址</span>
                  <input
                    value={draft.DEEPSEEK_BASE_URL}
                    onChange={(event) => update('DEEPSEEK_BASE_URL', event.target.value)}
                    placeholder="https://api.deepseek.com"
                  />
                </label>
                <label className="field">
                  <span>DeepSeek 模型</span>
                  <input
                    value={draft.DEEPSEEK_MODEL}
                    onChange={(event) => update('DEEPSEEK_MODEL', event.target.value)}
                    placeholder="deepseek-chat"
                  />
                </label>
                <label className="field">
                  <span>请求超时（秒）</span>
                  <input
                    value={draft.DEEPSEEK_TIMEOUT_SECONDS}
                    onChange={(event) => update('DEEPSEEK_TIMEOUT_SECONDS', event.target.value)}
                    placeholder="60"
                    inputMode="decimal"
                  />
                </label>
                <label className="field">
                  <span>
                    DeepSeek API Key
                    {status.deepseek.masked_key && (
                      <em className="field-existing">当前：{status.deepseek.masked_key}</em>
                    )}
                  </span>
                  <input
                    type="password"
                    value={secrets.DEEPSEEK_API_KEY}
                    onChange={(event) => updateSecret('DEEPSEEK_API_KEY', event.target.value)}
                    placeholder="留空表示不修改"
                    autoComplete="new-password"
                    spellCheck={false}
                  />
                </label>
                <div className="field actions-row">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={testing !== null}
                    onClick={() => void handleTest('deepseek')}
                  >
                    {testing === 'deepseek' ? '测试中…' : '测试连接'}
                  </button>
                  <span className="actions-hint">按当前表单值测，支持在 DeepSeek / Embedding 间分别测试，无需先保存</span>
                  {testResults.deepseek && (
                    <em className={isFailure(testResults.deepseek.status) ? 'field-existing test-bad' : 'field-existing'}>
                      测试结果：{testResults.deepseek.message ?? connectionLabel(testResults.deepseek.status)}
                    </em>
                  )}
                </div>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>语义检索（可选）</span>
                  <small>三项需同时具备才生效</small>
                </div>
                <label className="field">
                  <span>Embedding 服务地址</span>
                  <input
                    value={draft.EMBEDDING_BASE_URL}
                    onChange={(event) => update('EMBEDDING_BASE_URL', event.target.value)}
                    placeholder="留空则使用关键词检索"
                  />
                </label>
                <label className="field">
                  <span>Embedding 模型</span>
                  <input
                    value={draft.EMBEDDING_MODEL}
                    onChange={(event) => update('EMBEDDING_MODEL', event.target.value)}
                    placeholder="例如 text-embedding-3-small"
                  />
                </label>
                <label className="field">
                  <span>
                    Embedding API Key
                    {status.embedding.masked_key && (
                      <em className="field-existing">当前：{status.embedding.masked_key}</em>
                    )}
                  </span>
                  <input
                    type="password"
                    value={secrets.EMBEDDING_API_KEY}
                    onChange={(event) => updateSecret('EMBEDDING_API_KEY', event.target.value)}
                    placeholder="留空表示不修改"
                    autoComplete="new-password"
                    spellCheck={false}
                  />
                </label>
                <div className="field actions-row">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={testing !== null}
                    onClick={() => void handleTest('embedding')}
                  >
                    {testing === 'embedding' ? '测试中…' : '测试连接'}
                  </button>
                  {testResults.embedding && (
                    <em className={isFailure(testResults.embedding.status) ? 'field-existing test-bad' : 'field-existing'}>
                      测试结果：{testResults.embedding.message ?? connectionLabel(testResults.embedding.status)}
                    </em>
                  )}
                </div>
                <p className="field-hint">
                  三项（地址 / 密钥 / 模型）齐全后语义检索才会生效，否则自动回退为关键词检索。
                </p>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>本地存储</span>
                  <small>只读</small>
                </div>
                <label className="field">
                  <span>数据目录</span>
                  <input value={status.storage.data_dir} readOnly />
                </label>
                <label className="field">
                  <span>单文件上传上限（MB）</span>
                  <input
                    value={draft.NOTEBOOK_MAX_UPLOAD_MB}
                    onChange={(event) => update('NOTEBOOK_MAX_UPLOAD_MB', event.target.value)}
                    placeholder="50"
                    inputMode="numeric"
                  />
                </label>
                <label className="field">
                  <span>支持格式</span>
                  <input value={status.limits.allowed_extensions.join('、')} readOnly />
                </label>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>安全策略</span>
                  <small>运行时状态</small>
                </div>
                <div className="policy-list">
                  <div>
                    <span className={`policy-dot ${status.limits.secret_write_enabled ? 'dot-on' : 'dot-off'}`} />
                    密钥写入：{status.limits.secret_write_enabled ? '已允许' : '已禁用'}
                  </div>
                  <div>
                    <span className={`policy-dot ${status.limits.token_required ? 'dot-on' : 'dot-off'}`} />
                    设置口令：{status.limits.token_required ? '已配置' : '未配置'}
                  </div>
                  <div>
                    <span className="policy-dot dot-on" />
                    配置文件：{status.source.env_exists ? status.source.env_path : '尚未创建 .env'}
                  </div>
                </div>
                <details className="settings-details">
                  <summary>可修改的配置项（白名单）</summary>
                  <div className="key-chips">
                    {[...status.limits.editable_keys, 'DEEPSEEK_API_KEY', 'EMBEDDING_API_KEY'].map((key) => (
                      <span className="key-chip" key={key}>{key}</span>
                    ))}
                  </div>
                </details>
                {status.limits.secret_write_enabled && status.limits.token_required ? (
                  <label className="field">
                    <span>设置口令（写入密钥必需）</span>
                    <input
                      type="password"
                      value={token}
                      onChange={(event) => setToken(event.target.value)}
                      placeholder="在 .env 的 NOTEBOOK_SETTINGS_TOKEN 中配置"
                      autoComplete="off"
                    />
                  </label>
                ) : status.limits.secret_write_enabled ? (
                  <p className="field-hint">
                    本地模式已默认允许密钥写入：在上方直接填入 DeepSeek / Embedding Key 并保存即可，
                    无需编辑 .env。如需加固，可在 .env 中配置{' '}
                    <code>NOTEBOOK_SETTINGS_TOKEN</code> 开启口令校验。
                  </p>
                ) : (
                  <p className="field-hint">
                    要开启密钥写入，请在 .env 中设置 NOTEBOOK_ALLOW_SECRET_WRITE=true 与
                    NOTEBOOK_SETTINGS_TOKEN，重启后端后在 <code>data/backups/</code> 可找到每次写入前的备份。
                  </p>
                )}
              </section>
            </>
          )}
        </div>

        <footer className="settings-footer">
          <span className="settings-dirty">
            {changeCount > 0
              ? `${changeCount} 项待保存${secretTouched.length > 0 ? '（含密钥）' : ''}`
              : '暂无改动'}
          </span>
          <div>
            <button className="ghost-button" onClick={onClose}>取消</button>
            <button
              className="primary-button"
              onClick={() => void handleSave()}
              disabled={saving || changeCount === 0}
            >
              {saving ? '保存中…' : '保存配置'}
            </button>
          </div>
        </footer>
      </aside>
    </div>
  )
}
