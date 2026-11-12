// Ulanishlar holati (HRM) - foydalanuvchining O'Z hisobi. Faqat o'qish: HRM va CRM
// BRB-Tech ID bilan kirganda o'zi ulanadi (server: `apps/api/app/api/v1/auth.py`);
// login + parol bilan ulash 2026-11-12 da olib tashlandi. Javobda token yo'q -
// faqat holat. Mini App sozlamalari shuni ko'rsatadi.

import { apiFetch } from './http'
import type { ConnectorsResponse } from '../types'

export function listConnectors(): Promise<ConnectorsResponse> {
  return apiFetch<ConnectorsResponse>('/api/v1/connectors')
}
