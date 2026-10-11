/**
 * Ilova servislari (API, sessiya, navbat, uploader) - bitta joyda yig'iladi.
 *
 * NIMA UCHUN kontekst: ekran testlari soxta API bilan `ServicesProvider`
 * ga beriladi; ilovada `createAppServices()` haqiqiy native modullar bilan.
 * Background task ham shu `getAppServices()` ni ishlatadi.
 */
import Constants from 'expo-constants';
import { createContext, useContext, type ReactNode } from 'react';
import { Platform } from 'react-native';

import { createActionsApi, type ActionsApi } from '@/api/actions';
import { createChatApi, type ChatApi } from '@/api/chat';
import { ApiClient } from '@/api/client';
import { createAuthApi, createMeetingsApi, type AuthApi, type MeetingsApi } from '@/api/meetings';
import type { RegisterDeviceRequest } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { callConsent } from '@/features/calls/callsStore';
import { createSession, type Session } from '@/features/auth/session';
import { createTokenStore, type TokenStore } from '@/features/auth/tokenStore';
import { isFileInUse } from '@/features/meeting/playback';
import { useSettings } from '@/features/settings/settingsStore';
import type { QueueStore } from '@/features/upload/queueStore';
import { createUploader, type FileAccess, type Uploader } from '@/features/upload/uploader';

export interface Services {
  apiBaseUrl: string;
  client: ApiClient;
  /** Barno bilan suhbat (asosiy ekran): oqim, tarix, ulanishlar, Pro, diktovka. */
  chat: ChatApi;
  meetings: MeetingsApi;
  /** Taklifni tasdiqlash / rad etish (`/api/v1/actions`) - chat bilan bir xil yo'l. */
  actions: ActionsApi;
  auth: AuthApi;
  session: Session;
  tokens: TokenStore;
  queue: QueueStore;
  uploader: Uploader;
  files: FileAccess;
  appVersion: string;
  deviceName: string;
}

export function apiBaseUrlFromConfig(): string {
  const extra = (Constants.expoConfig?.extra ?? {}) as { apiBaseUrl?: string };
  return (extra.apiBaseUrl || 'https://llm.brb-tech.uz').replace(/\/+$/, '');
}

/** Qurilmani ro'yxatdan o'tkazish ma'lumoti (native login ham, Mini App tokeni ham). */
export function deviceInfo(services: Pick<Services, 'deviceName' | 'appVersion'>): RegisterDeviceRequest {
  return {
    deviceName: services.deviceName.slice(0, 80) || 'android',
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    appVersion: services.appVersion,
  };
}

let appServices: Promise<Services> | null = null;

/** Ilova (va background task) uchun yagona nusxa. Native modullar shu yerda yuklanadi. */
export function getAppServices(): Promise<Services> {
  if (!appServices) {
    appServices = createAppServices().catch((e) => {
      appServices = null;
      throw e;
    });
  }
  return appServices;
}

async function createAppServices(): Promise<Services> {
  /* eslint-disable @typescript-eslint/no-require-imports */
  const SecureStore = require('expo-secure-store') as typeof import('expo-secure-store');
  const SQLite = require('expo-sqlite') as typeof import('expo-sqlite');
  const Crypto = require('expo-crypto') as typeof import('expo-crypto');
  const Device = require('expo-device') as typeof import('expo-device');
  const Application = require('expo-application') as typeof import('expo-application');
  const FS = require('expo-file-system') as typeof import('expo-file-system');
  const { createSqliteQueueStore } = require('@/features/upload/queueStore') as typeof import('@/features/upload/queueStore');
  const { createMemoryQueueStore } = require('@/features/upload/queueStore.memory') as typeof import('@/features/upload/queueStore.memory');
  const { recordingFile } = require('@/lib/paths') as typeof import('@/lib/paths');
  const { yieldToUi } = require('@/lib/appState') as typeof import('@/lib/appState');
  /* eslint-enable @typescript-eslint/no-require-imports */

  const apiBaseUrl = apiBaseUrlFromConfig();
  const client = new ApiClient({ baseUrl: apiBaseUrl, getLanguage: () => useSettings.getState().uiLang });
  const auth = createAuthApi(client);
  const meetings = createMeetingsApi(client);
  const actions = createActionsApi(client);
  const chat = createChatApi(client);
  const tokens = createTokenStore({
    getItemAsync: (k) => SecureStore.getItemAsync(k),
    setItemAsync: (k, v) => SecureStore.setItemAsync(k, v),
    deleteItemAsync: (k) => SecureStore.deleteItemAsync(k),
  });
  const session = createSession({ store: tokens, authApi: auth });
  client.setTokenProvider(session);
  session.subscribe((e) => {
    if (e === 'expired') useAuth.getState().setSignedOut(true);
    if (e === 'signedOut') useAuth.getState().setSignedOut(false);
  });

  let queue: QueueStore;
  try {
    const db = await SQLite.openDatabaseAsync('venera-queue.db');
    queue = await createSqliteQueueStore(db);
  } catch {
    // SQLite ochilmasa ham yozish ishlasin (navbat faqat xotirada qoladi).
    queue = createMemoryQueueStore();
  }

  const files: FileAccess = {
    async size(uri) {
      const f = new FS.File(uri);
      if (!f.exists) return null;
      return f.size;
    },
    async read(uri, offset, length) {
      const h = new FS.File(uri).open(FS.FileMode.ReadOnly);
      try {
        h.offset = offset;
        return h.readBytes(length);
      } finally {
        h.close();
      }
    },
    async remove(uri) {
      try {
        const f = new FS.File(uri);
        if (f.exists) f.delete();
      } catch {
        /* allaqachon yo'q */
      }
    },
  };

  const appVersion = Application.nativeApplicationVersion ?? Constants.expoConfig?.version ?? '1.0.0';
  const deviceName = Device.modelName ?? Device.deviceName ?? 'android';

  const uploader = createUploader({
    store: queue,
    api: meetings,
    files,
    async chunkSha256(bytes) {
      const buf = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes as Uint8Array<ArrayBuffer>);
      return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, '0')).join('');
    },
    keepDays: () => useSettings.getState().keepDays,
    fileInUse: isFileInUse,
    callConsent,
    canonicalUri: (clientId) => recordingFile(clientId).uri,
    yieldToUi,
    appVersion,
    device: deviceName,
    onAuthRequired: () => {
      // Faqat kirgan foydalanuvchi uchun "sessiya tugadi"; kirmasdan yozganlar uchun jim.
      if (useAuth.getState().status === 'signedIn') useAuth.getState().setSignedOut(true);
    },
  });

  return { apiBaseUrl, client, chat, meetings, actions, auth, session, tokens, queue, uploader, files, appVersion, deviceName };
}

const ServicesContext = createContext<Services | null>(null);

export function ServicesProvider({ services, children }: { services: Services; children: ReactNode }) {
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

export function useServices(): Services {
  const s = useContext(ServicesContext);
  if (!s) throw new Error('ServicesProvider yo\'q');
  return s;
}
