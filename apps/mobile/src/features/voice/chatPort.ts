/**
 * Ovozli sessiya <-> chat dvigateli (`useChat`). Savol ODDIY chatning o'zi orqali ketadi:
 * xuddi shu `chatId`, tarix, Pro va davomli savollar xotirasi - ovozli suhbatdan chiqqach
 * savol-javoblar chat ekranida turadi.
 */
import type { ChatStreamFn } from '@/features/chat/chatStore';
import { useChat } from '@/features/chat/chatStore';

import type { ChatPort } from './ports';

export function createChatPort(stream: ChatStreamFn): ChatPort {
  return {
    sendVoice: (text) => useChat.getState().sendVoice(text, stream),
    stop: () => useChat.getState().stop(),
    exchange: (id) => useChat.getState().exchanges.find((e) => e.id === id),
    busy: () => useChat.getState().phase !== 'idle',
    subscribe: (listener) => useChat.subscribe(() => listener()),
  };
}
