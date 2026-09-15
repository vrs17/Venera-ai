// Ulanishlar (HRM / CRM) - foydalanuvchining O'Z hisobi. Faqat HTTP; holat
// `composables/useConnectors.ts` da.
//
// Parol shu yerdan serverga ketadi va HECH QAYERDA saqlanmaydi (serverda
// ham: u platformaga login uchun ishlatiladi va unutiladi). Javobda token
// yo'q - faqat holat: brauzer HRM/CRM tokenini hech qachon ko'rmaydi.

import { apiFetch } from './http'
import type { ConnectorId, ConnectorStatus, ConnectorsResponse, ConnectRequest, ConnectorUpdate } from '../types'

export function listConnectors(): Promise<ConnectorsResponse> {
  return apiFetch<ConnectorsResponse>('/api/v1/connectors')
}

export function connectConnector(id: ConnectorId, data: ConnectRequest): Promise<ConnectorStatus> {
  return apiFetch<ConnectorStatus>(`/api/v1/connectors/${id}/connect`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function updateConnector(id: ConnectorId, data: ConnectorUpdate): Promise<ConnectorStatus> {
  return apiFetch<ConnectorStatus>(`/api/v1/connectors/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
}

export function disconnectConnector(id: ConnectorId): Promise<ConnectorStatus> {
  return apiFetch<ConnectorStatus>(`/api/v1/connectors/${id}`, { method: 'DELETE' })
}
