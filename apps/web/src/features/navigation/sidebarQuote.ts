import { readStorage, writeStorage } from '../../utils/safeStorage'

export const DEFAULT_SIDEBAR_QUOTE = '每一页积累，\n都在悄悄生长。'
export const SIDEBAR_QUOTE_MAX_LENGTH = 80
const STORAGE_KEY = 'notebuddy.sidebar-quote'

export function readSidebarQuote(): string {
  return readStorage(STORAGE_KEY)?.trim() || DEFAULT_SIDEBAR_QUOTE
}

export function saveSidebarQuote(value: string): string {
  const quote = value.replace(/\r\n?/g, '\n').trim().slice(0, SIDEBAR_QUOTE_MAX_LENGTH) || DEFAULT_SIDEBAR_QUOTE
  writeStorage(STORAGE_KEY, quote)
  if (readStorage(STORAGE_KEY) !== quote) {
    throw new Error('浏览器无法保存寄语，请允许本地存储后重试。')
  }
  return quote
}
