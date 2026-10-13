// Qadam turlari: belgi (lucide - admin panelning qolgan joylari bilan bir xil) va rang.
// Rang - admin tokenlaridan (`--viz-*`, `--brand`...): yorug' va qorong'i mavzuda
// o'zi almashadi, alohida palitra kerak emas. Noma'lum tur - `service` sifatida.

import type { Component } from 'vue'
import {
  AppWindow,
  ArrowRightToLine,
  Box,
  Clock,
  Database,
  Diamond,
  Globe,
  MessageCircle,
  SlidersHorizontal,
  Sparkles,
  User,
  Wrench,
} from 'lucide-vue-next'
import type { OsKind } from './types'

export interface KindStyle {
  icon: Component
  /** CSS rang qiymati (token). */
  color: string
}

export const KINDS: Record<OsKind, KindStyle> = {
  user: { icon: User, color: 'var(--viz-1)' },
  channel: { icon: MessageCircle, color: 'var(--viz-1)' },
  ui: { icon: AppWindow, color: 'var(--viz-seq-3)' },
  endpoint: { icon: ArrowRightToLine, color: 'var(--text-3)' },
  service: { icon: Box, color: 'var(--viz-3)' },
  decision: { icon: Diamond, color: 'var(--viz-4)' },
  llm: { icon: Sparkles, color: 'var(--brand)' },
  tool: { icon: Wrench, color: 'var(--viz-6)' },
  store: { icon: Database, color: 'var(--warn-text)' },
  external: { icon: Globe, color: 'var(--viz-7)' },
  job: { icon: Clock, color: 'var(--info-text)' },
  config: { icon: SlidersHorizontal, color: 'var(--viz-5)' },
}

export const KIND_ORDER = Object.keys(KINDS) as OsKind[]

export function kindOf(kind: string | undefined): OsKind {
  return kind && kind in KINDS ? (kind as OsKind) : 'service'
}
