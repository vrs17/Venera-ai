// Write actions the assistant proposed. Only HTTP; the card under the answer
// owns the state.
//
// The browser sends ONLY the action token. Who confirms (the Venera user) and
// the platform token the action needs are added by our backend — the same
// identity that was used when the action was proposed, so nobody can confirm
// somebody else's proposal.

import { apiFetch } from './http'
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
