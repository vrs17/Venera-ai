// Kanal -> belgi va rang. Rang OB'EKTGA bog'langan (spec §1.3): "Bot" har bir grafikda,
// nishonda va afsonada bir xil yashil - rangni ko'rgan odam kanalni tanishi uchun.
// Shu sababli rang faqat shu yerdan olinadi, sahifalar o'zi tanlamaydi.
//
//   import { channelIcon, channelColor } from '../components/channel'
//   <component :is="channelIcon(turn.channel)" />   style="--c: var(--ch-bot)"

import type { Component } from 'vue'
import { AppWindow, Braces, Bot, Globe, Monitor, Server } from 'lucide-vue-next'
import { CHANNELS } from '../types'
import type { Channel } from '../types'

const ICONS: Record<Channel | 'system', Component> = {
  web: Globe,
  miniapp: AppWindow,
  bot: Bot,
  desktop: Monitor,
  api: Braces,
  system: Server,
}

export function isKnownChannel(v: unknown): v is Channel {
  return typeof v === 'string' && (CHANNELS as readonly string[]).includes(v)
}

/** Kanal belgisi; noma'lum qiymat - `api` belgisi (serverdan kelgan yangi kanal ham chizilsin). */
export function channelIcon(channel: string | null | undefined): Component {
  if (channel === 'system') return ICONS.system
  return isKnownChannel(channel) ? ICONS[channel] : ICONS.api
}

/**
 * Kanal rangi - grafiklar uchun CSS o'zgaruvchi NOMI (`'--ch-web'`), chart primitivlari
 * `color` propida aynan shuni kutadi. `system` (foydalanuvchisiz chaqiruvlar) va noma'lum
 * kanal - jim kulrang: ular "boshqa" toifasi, alohida rang talab qilmaydi.
 */
export function channelColor(channel: string | null | undefined): string {
  return isKnownChannel(channel) ? `--ch-${channel}` : '--text-4'
}
