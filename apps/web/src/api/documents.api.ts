// Document template + generation endpoints (EMPLOYEE-only on the backend).

import { ApiError, BASE_URL, apiFetch, getToken } from './http'
import type {
  DocumentGenerationRequest,
  DocumentGenerationResponse,
  DocumentTemplate,
  DocumentTemplateSummary,
} from '../types'

export function listTemplates(): Promise<DocumentTemplateSummary[]> {
  return apiFetch<DocumentTemplateSummary[]>('/api/v1/documents/templates')
}

export function getTemplate(documentType: string): Promise<DocumentTemplate> {
  return apiFetch<DocumentTemplate>(`/api/v1/documents/templates/${encodeURIComponent(documentType)}`)
}

export function generateDocument(data: DocumentGenerationRequest): Promise<DocumentGenerationResponse> {
  return apiFetch<DocumentGenerationResponse>('/api/v1/documents/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  // RFC 5987 ext-value: filename*=charset'lang'value (lang may be non-empty,
  // e.g. UTF-8'en'report.docx), OR the plain filename="name.docx" form.
  const star = /filename\*=[^']*'[^']*'([^;]+)/i.exec(header)
  if (star) {
    const v = star[1].trim()
    try {
      return decodeURIComponent(v)
    } catch {
      return v
    }
  }
  const plain = /filename=["']?([^"';]+)/i.exec(header)
  return plain ? plain[1] : fallback
}

/**
 * Download the generated DOCX. The endpoint requires the Bearer header, so a
 * plain window.open / anchor navigation can't be used — fetch with auth, then
 * save the blob via a transient anchor.
 */
export async function downloadDocument(downloadUrl: string, fallbackName = 'document.docx'): Promise<void> {
  const token = getToken()
  const res = await fetch(`${BASE_URL}${downloadUrl}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new ApiError(`Download failed (${res.status})`)
  const blob = await res.blob()
  const name = filenameFromDisposition(res.headers.get('content-disposition'), fallbackName)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
