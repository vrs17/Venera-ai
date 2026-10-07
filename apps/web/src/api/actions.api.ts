// Write actions the assistant proposed. Only HTTP; the card under the answer
// owns the state.
//
// The browser sends ONLY the action token. Who confirms (the Venera user) and
// the platform token the action needs are added by our backend — the same
// identity that was used when the action was proposed, so nobody can confirm
// somebody else's proposal.

import { ApiError, apiFetch } from './http'
import type { ActionResult } from '../types'

export function confirmAction(token: string): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/api/v1/actions/${encodeURIComponent(token)}/confirm`, { method: 'POST' })
}

export function cancelAction(token: string): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/api/v1/actions/${encodeURIComponent(token)}/cancel`, { method: 'POST' })
}

export function getAction(token: string): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/api/v1/actions/${encodeURIComponent(token)}`)
}

/**
 * The proposal can no longer be confirmed: the backend answers 404 (unknown
 * token) or 410 (`expired`, since 2026-10; proposals live 15 minutes). The card
 * shows "expired" for these instead of a service error.
 */
export function isExpiredError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 410)
}

/**
 * Human-readable name of the proposal's target ("DVSIB-123", a project name).
 * Empty when there is none — e.g. a NEW issue (`{kind: "new_issue", key: null}`):
 * its title and project are already listed as changes, and the raw JSON row
 * the card used to fall back to was noise.
 */
export function targetLabel(target: unknown): string {
  if (target == null || target === '') return ''
  if (typeof target !== 'object') return String(target)
  const o = target as Record<string, unknown>
  const name = o.title ?? o.name ?? o.key ?? o.id
  return name != null && name !== '' ? String(name) : ''
}
