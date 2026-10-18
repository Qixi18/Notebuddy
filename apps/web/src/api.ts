import { configApi } from './api/config'
import { courseApi } from './api/courses'
import { knowledgeApi } from './api/knowledge'
import { materialApi } from './api/materials'
import { noteApi } from './api/notes'
import { notebookApi } from './api/notebook'
import { conversationApi } from './api/conversations'
import { feedbackApi } from './api/feedback'
import { termsApi } from './api/terms'
import { forestApi } from './api/forest'

export { ApiError } from './api/http'
export type { Capabilities, ConnectivityTestPayload, OCRStatus, ProviderStatus } from './api/config'

export const api = {
  ...forestApi,
  ...courseApi,
  ...materialApi,
  ...noteApi,
  ...notebookApi,
  ...knowledgeApi,
  ...configApi,
  ...conversationApi,
  ...feedbackApi,
  ...termsApi,
}
