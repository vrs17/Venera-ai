/**
 * Barno XOTIRASI (yordamchi 3.3, web/Mini App bilan bir qoida): API yo'llari va tolerant
 * o'qish, xato turlari (404 `memory_not_found` - allaqachon yo'q; kodsiz 404 - xizmat yo'q),
 * "Xotira" sahifasi (ro'yxat, qator ichidagi tasdiq, hammasini unutish - kuchli tasdiq,
 * bo'sh holat namunalari, yuklash xatosi) va Sozlamalar hub'idagi "Xotira" qatori.
 * Tarmoq yo'q: soxta fetch (`fixtures/fakeFetch`).
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import { AccessibilityInfo, StyleSheet } from 'react-native';

import { assistantErrorKind, createAssistantApi, FORGET_ALL_CONFIRM, type MemoryItem } from '@/api/assistant';
import { ApiError, ApiClient } from '@/api/client';
import MemoryScreen from '@/app/settings/memory';
import SettingsScreen from '@/app/settings/index';
import { useAuth } from '@/features/auth/authStore';
import { byRecent, forgetAllHint, memoryOriginKey } from '@/features/settings/assistant';
import { useSettings } from '@/features/settings/settingsStore';
import { makeT } from '@/i18n';
import type { Services } from '@/services';
import { showToast } from '@/ui/errors';

import { envelope, fakeFetch, type FakeReply, type FakeRequest, type Handler } from './fixtures/fakeFetch';
import { fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn() },
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
  };
});
// Hub "Tez yozish" qatori native modulni o'qiydi - testda modul yo'q (Jest/iOS kabi).
jest.mock('@/features/entry/nativeEntry', () => ({
  isAvailable: jest.fn(() => false),
  isLauncherEnabled: jest.fn(() => false),
  isKeyServiceEnabled: jest.fn(() => false),
  setLauncherEnabled: jest.fn(),
  requestAddTile: jest.fn(async () => 'unsupported'),
  openAccessibilitySettings: jest.fn(),
  setRecordingState: jest.fn(),
  setTrustedKey: jest.fn(),
}));
jest.mock('@/ui/errors', () => ({ ...jest.requireActual('@/ui/errors'), showToast: jest.fn() }));

const t = makeT('uz');
const flat = (el: { props: { style?: unknown } }) => (StyleSheet.flatten(el.props.style as never) ?? {}) as Record<string, unknown>;

const ITEMS = [
  { id: 'm1', text: 'Chilonzor filialida ishlaydi', kind: 'fact', source: 'user', created_at: '2026-10-01T09:00:00Z', updated_at: null },
  { id: 'm2', text: 'Javoblarni qisqa yoqtiradi', kind: 'preference', source: 'learned', created_at: '2026-10-09T09:00:00Z', updated_at: '2026-10-09T10:00:00Z' },
  { id: 'h3f2a', text: 'Dushanba kuni hisobot topshiradi', kind: 'routine', source: 'learned', created_at: '', updated_at: '' },
];

function clientWith(handler: Handler) {
  const { fetch, calls } = fakeFetch(handler);
  const client = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: { getToken: async () => 'jwt', refreshToken: async () => 'jwt2' } });
  return { client, calls };
}

/** Xotira yo'llari uchun oddiy "server": ro'yxat, bitta va hammasini o'chirish. */
function memoryServer(initial: unknown[] = ITEMS, over: Partial<Record<'list' | 'delete' | 'wipe', (req: FakeRequest) => FakeReply>> = {}) {
  let items = [...initial] as { id: string }[];
  const handler: Handler = (req) => {
    if (req.path === '/api/v1/assistant/memory' && req.method === 'GET') return over.list?.(req) ?? { json: { items, count: items.length } };
    if (req.path === '/api/v1/assistant/memory' && req.method === 'DELETE') {
      if (over.wipe) return over.wipe(req);
      const deleted = items.map((m) => m.id);
      items = [];
      return { json: { deleted, status: 'deleted' } };
    }
    const m = /^\/api\/v1\/assistant\/memory\/(.+)$/.exec(req.path);
    if (m && req.method === 'DELETE') {
      if (over.delete) return over.delete(req);
      items = items.filter((x) => x.id !== decodeURIComponent(m[1]));
      return { json: { deleted: [decodeURIComponent(m[1])], status: 'deleted' } };
    }
    if (req.path === '/api/v1/connectors') return { json: { connectors: [] } };
    return envelope(404, 'yo\'q');
  };
  return handler;
}

async function renderWith(Screen: () => React.ReactNode, handler: Handler) {
  const { client, calls } = clientWith(handler);
  const services: Services = { ...fakeServices(), client };
  await render(
    <Providers services={services}>
      <Screen />
    </Providers>,
  );
  return { services, calls };
}

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
  useAuth.getState().setSignedIn({
    actorId: 7,
    actorType: 'EMPLOYEE',
    email: 'y@brb.uz',
    fullName: 'Yusuf Mamajonov',
    position: null,
    department: null,
    roles: [],
    passwordChangeRequired: false,
  });
  useAuth.getState().setConfig(null);
});

describe('assistant API (memory)', () => {
  it('lists memory tolerantly: drops items without id or text, trims, reads camelCase dates', async () => {
    const { client, calls } = clientWith(() => ({
      json: {
        items: [
          { id: 'm1', text: '  Salom  ', createdAt: '2026-10-01T00:00:00Z' },
          { id: '', text: 'kalitsiz' },
          { id: 'm2', text: '   ' },
          { id: 12, text: 'raqamli kalit' },
          'buzuq',
        ],
        count: 5,
      },
    }));
    const list = await createAssistantApi(client).listMemory();
    expect(list.items.map((m) => [m.id, m.text, m.kind, m.source, m.created_at])).toEqual([
      ['m1', 'Salom', 'fact', 'learned', '2026-10-01T00:00:00Z'],
      ['12', 'raqamli kalit', 'fact', 'learned', null],
    ]);
    expect(calls[0]).toMatchObject({ method: 'GET', path: '/api/v1/assistant/memory' });
    // Kimlik so'rovda YO'Q - backend uni sessiyadan qo'yadi.
    expect(calls[0].query).toEqual({});
    expect(calls[0].headers.Authorization).toBe('Bearer jwt');
  });

  it('forget-all carries the exact confirm phrase; forget-one encodes the id', async () => {
    const { client, calls } = clientWith((req) => ({ json: req.query.confirm ? { deleted: ['a', 'b'] } : { deleted: ['x/y'], status: 'deleted' } }));
    const api = createAssistantApi(client);
    expect(await api.forgetAllMemory()).toEqual({ deleted: ['a', 'b'], status: 'deleted' });
    expect(calls[0]).toMatchObject({ method: 'DELETE', path: '/api/v1/assistant/memory', query: { confirm: 'forget-all' } });
    expect(FORGET_ALL_CONFIRM).toBe('forget-all');
    await api.deleteMemoryItem('x/y');
    expect(calls[1].method).toBe('DELETE');
    expect(calls[1].url).toBe('https://x.uz/api/v1/assistant/memory/x%2Fy');
    expect(calls[1].query).toEqual({});
  });

  it('error kinds: coded 404 = already gone, bare 404 = service missing, 429, 5xx, network', () => {
    expect(assistantErrorKind(new ApiError(404, 'memory_not_found', 'x'))).toBe('notFound');
    expect(assistantErrorKind(new ApiError(404, 'platform_not_found', 'x'))).toBe('notFound');
    // Kodsiz 404 (yo'l yo'q - API hali chiqmagan, nginx) "unutildi" deb o'qilmaydi.
    expect(assistantErrorKind(new ApiError(404, 'not_found', 'x'))).toBe('unavailable');
    expect(assistantErrorKind(new ApiError(429, 'rate_limited', 'x'))).toBe('rateLimited');
    expect(assistantErrorKind(new ApiError(503, 'upstream_unavailable', 'x'))).toBe('unavailable');
    expect(assistantErrorKind(new ApiError(504, 'upstream_timeout', 'x'))).toBe('unavailable');
    expect(assistantErrorKind(new ApiError(0, 'network', 'x'))).toBe('network');
    expect(assistantErrorKind(new ApiError(0, 'timeout', 'x'))).toBe('unavailable');
    expect(assistantErrorKind(new ApiError(400, 'confirm_required', 'x'))).toBe('generic');
    expect(assistantErrorKind(new Error('x'))).toBe('generic');
  });
});

describe('memory helpers', () => {
  const items = ITEMS as MemoryItem[];

  it('newest first, undated last in server order; origin by source/kind', () => {
    expect(byRecent(items).map((m) => m.id)).toEqual(['m2', 'm1', 'h3f2a']);
    expect(items.map((m) => t(memoryOriginKey(m)))).toEqual([
      "Siz eslab qolishni so'ragansiz",
      "Savollaringizdan o'rganilgan",
      "CRM vazifalaringizdan o'rganilgan",
    ]);
  });

  it('forget-all hint names the count and mentions CRM routines only when there is one', () => {
    expect(forgetAllHint(items, t)).toBe(
      "Barno siz haqingizda eslab qolgan 3 ta narsaning hammasini unutadi. Suhbatlar tarixi saqlanib qoladi. CRM vazifalaringizdan o'rganganlari ham unutiladi.",
    );
    expect(forgetAllHint(items.slice(0, 2), t)).not.toMatch(/CRM/);
    expect(forgetAllHint(items.slice(0, 2), makeT('ru'))).toBe('Барно забудет всё, что помнит о вас (2 шт.). Чаты останутся.');
  });
});

describe('Memory screen', () => {
  it('lists items newest first with origin and date; the lead says only you see it', async () => {
    await renderWith(MemoryScreen, memoryServer());
    expect(await screen.findByText('Javoblarni qisqa yoqtiradi')).toBeTruthy();
    expect(screen.getByText(/faqat siz ko'rasiz/)).toBeTruthy();
    const rows = within(screen.getByTestId('memory-list')).getAllByTestId(/^memory-(m1|m2|h3f2a)$/);
    expect(rows.map((r) => r.props.testID)).toEqual(['memory-m2', 'memory-m1', 'memory-h3f2a']);
    expect(within(rows[0]).getByText("Savollaringizdan o'rganilgan · 9-oktabr")).toBeTruthy();
    expect(within(rows[1]).getByText("Siz eslab qolishni so'ragansiz · 1-oktabr")).toBeTruthy();
    // Sanasiz (CRM tartibi) - faqat kelib chiqishi.
    expect(within(rows[2]).getByText("CRM vazifalaringizdan o'rganilgan")).toBeTruthy();
    expect(screen.getByText(/«eslab qol \.\.\.» yoki «\.\.\. ni unut»/)).toBeTruthy();
  });

  it('delete one: confirm inside the row; cancel keeps it, "Unutish" deletes and toasts', async () => {
    const { calls } = await renderWith(MemoryScreen, memoryServer());
    await screen.findByText('Javoblarni qisqa yoqtiradi');
    const trash = screen.getByTestId('memory-forget-m1');
    expect(trash.props.accessibilityLabel).toBe('Unutish: Chilonzor filialida ishlaydi');
    await fireEvent.press(trash);
    const box = screen.getByTestId('memory-confirm-m1');
    expect(within(box).getByText('Barno buni unutsinmi?')).toBeTruthy();
    expect(within(box).getByText(/qaytarib bo'lmaydi/)).toBeTruthy();
    // Bitta bosish o'chirmaydi.
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    await fireEvent.press(screen.getByTestId('memory-keep-m1'));
    expect(screen.queryByTestId('memory-confirm-m1')).toBeNull();

    await fireEvent.press(screen.getByTestId('memory-forget-m1'));
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-forget-yes-m1'));
    });
    await waitFor(() => expect(screen.queryByText('Chilonzor filialida ishlaydi')).toBeNull());
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/v1/assistant/memory/m1']);
    expect(showToast).toHaveBeenCalledWith('Unutildi');
    expect(screen.getByText('Javoblarni qisqa yoqtiradi')).toBeTruthy();
  });

  it('TalkBack: the trash moves focus to the confirm question; "Bekor qilish" moves it back to the trash', async () => {
    const send = AccessibilityInfo.sendAccessibilityEvent as jest.Mock;
    await renderWith(MemoryScreen, memoryServer());
    await screen.findByText('Javoblarni qisqa yoqtiradi');
    expect(send).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId('memory-forget-m1'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    const [question, kind] = send.mock.calls[0];
    expect(kind).toBe('focus');
    expect(question).toBeTruthy();
    await fireEvent.press(screen.getByTestId('memory-keep-m1'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1][1]).toBe('focus');
    expect(send.mock.calls[1][0]).not.toBe(question);
  });

  it('a list refresh that was in flight does not bring a forgotten item back', async () => {
    let gets = 0;
    let releaseStale: () => void = () => {};
    const base = memoryServer();
    await renderWith(MemoryScreen, async (req) => {
      if (req.path === '/api/v1/assistant/memory' && req.method === 'GET' && ++gets === 2) {
        // Eski javob: o'chirishdan OLDIN boshlangan yuklash - hali m1 bor.
        await new Promise<void>((r) => (releaseStale = r));
        return { json: { items: ITEMS, count: ITEMS.length } };
      }
      return base(req);
    });
    await screen.findByText('Chilonzor filialida ishlaydi');
    // Pastga tortish - javob ushlab turiladi (await qilinmaydi).
    await act(async () => {
      void screen.getByTestId('memory-screen').props.refreshControl.props.onRefresh();
    });
    await waitFor(() => expect(gets).toBe(2));
    await fireEvent.press(screen.getByTestId('memory-forget-m1'));
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-forget-yes-m1'));
    });
    await waitFor(() => expect(screen.queryByText('Chilonzor filialida ishlaydi')).toBeNull());
    await act(async () => {
      releaseStale();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByText('Chilonzor filialida ishlaydi')).toBeNull();
    expect(screen.getByText('Javoblarni qisqa yoqtiradi')).toBeTruthy();
  });

  it('404 memory_not_found = already forgotten: the row goes away, no error', async () => {
    await renderWith(
      MemoryScreen,
      memoryServer(ITEMS, { delete: () => envelope(404, 'Bu xotira bandi topilmadi', { code: 'memory_not_found' }) }),
    );
    await screen.findByText('Javoblarni qisqa yoqtiradi');
    await fireEvent.press(screen.getByTestId('memory-forget-m2'));
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-forget-yes-m2'));
    });
    await waitFor(() => expect(screen.queryByText('Javoblarni qisqa yoqtiradi')).toBeNull());
    expect(showToast).toHaveBeenCalledWith('Unutildi');
  });

  it('a bare 404 (route missing) or 429 is NOT "forgotten": the row and its confirm stay, the toast says why', async () => {
    let reply: FakeReply = envelope(404, 'Not Found');
    await renderWith(MemoryScreen, memoryServer(ITEMS, { delete: () => reply }));
    await screen.findByText('Javoblarni qisqa yoqtiradi');
    await fireEvent.press(screen.getByTestId('memory-forget-m2'));
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-forget-yes-m2'));
    });
    expect(showToast).toHaveBeenLastCalledWith("Unutib bo'lmadi. Barno hozir javob bermayapti. Birozdan so'ng urinib ko'ring.");
    expect(screen.getByText('Javoblarni qisqa yoqtiradi')).toBeTruthy();
    expect(screen.getByTestId('memory-confirm-m2')).toBeTruthy();
    reply = envelope(429, 'ko\'p', { code: 'rate_limited' });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-forget-yes-m2'));
    });
    expect(showToast).toHaveBeenLastCalledWith("Unutib bo'lmadi. So'rovlar juda ko'p. Biroz kutib, qayta urinib ko'ring.");
    expect(showToast).not.toHaveBeenCalledWith('Unutildi');
  });

  it('forget all: strong confirm with the count; disabled until "I understand"; clears to the empty state', async () => {
    const { calls } = await renderWith(MemoryScreen, memoryServer());
    await screen.findByText('Javoblarni qisqa yoqtiradi');
    await fireEvent.press(screen.getByTestId('memory-forget-all'));
    const sheet = screen.getByTestId('memory-wipe');
    expect(within(sheet).getByText('Barno hammasini unutsinmi?')).toBeTruthy();
    expect(screen.getByTestId('memory-wipe-hint').props.children).toMatch(/3 ta narsaning hammasini.*CRM vazifalaringizdan/);
    const yes = screen.getByTestId('memory-wipe-yes');
    expect(yes).toBeDisabled();
    await fireEvent.press(yes);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);

    await fireEvent.press(screen.getByTestId('memory-wipe-ack'));
    expect(screen.getByTestId('memory-wipe-ack')).toBeChecked();
    expect(screen.getByTestId('memory-wipe-yes')).not.toBeDisabled();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-wipe-yes'));
    });
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => [c.path, c.query])).toEqual([['/api/v1/assistant/memory', { confirm: 'forget-all' }]]);
    expect(await screen.findByTestId('memory-empty')).toBeTruthy();
    expect(screen.queryByTestId('memory-wipe')).toBeNull();
    expect(showToast).toHaveBeenCalledWith('Xotira tozalandi');
  });

  it('forget all: the checkbox starts unchecked every time; a failure keeps the list and says why', async () => {
    await renderWith(MemoryScreen, memoryServer(ITEMS, { wipe: () => envelope(503, 'band', { code: 'upstream_unavailable' }) }));
    await screen.findByText('Javoblarni qisqa yoqtiradi');
    await fireEvent.press(screen.getByTestId('memory-forget-all'));
    await fireEvent.press(screen.getByTestId('memory-wipe-ack'));
    await fireEvent.press(screen.getByTestId('memory-wipe-cancel'));
    expect(screen.queryByTestId('memory-wipe')).toBeNull();
    await fireEvent.press(screen.getByTestId('memory-forget-all'));
    expect(screen.getByTestId('memory-wipe-ack')).not.toBeChecked();
    expect(screen.getByTestId('memory-wipe-yes')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('memory-wipe-ack'));
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-wipe-yes'));
    });
    expect(showToast).toHaveBeenLastCalledWith("Xotirani tozalab bo'lmadi. Barno hozir javob bermayapti. Birozdan so'ng urinib ko'ring.");
    expect(screen.getByText('Chilonzor filialida ishlaydi')).toBeTruthy();
  });

  it('empty state: what Barno can remember + muted italic example phrases (quotes, not bubbles)', async () => {
    await renderWith(MemoryScreen, memoryServer([]));
    expect(await screen.findByText('Barno hali hech narsani eslab qolmagan')).toBeTruthy();
    const examples = screen.getAllByTestId('memory-example');
    expect(examples.map((e) => e.props.children)).toEqual(['«Eslab qol: men Chilonzor filialida ishlayman»', '«Filialimni unut»']);
    for (const e of examples) {
      expect(flat(e).fontStyle).toBe('italic');
      // Bosiladigan narsa emas (chatdagi pufakchaga o'xshamasin).
      expect(e.props.onPress).toBeUndefined();
    }
    expect(screen.queryByTestId('memory-forget-all')).toBeNull();
  });

  it('load error -> retry', async () => {
    let fail = true;
    await renderWith(MemoryScreen, memoryServer(ITEMS, { list: () => (fail ? envelope(502, 'x', { code: 'upstream_error' }) : { json: { items: ITEMS, count: 3 } }) }));
    expect(await screen.findByText("Xotirani yuklab bo'lmadi")).toBeTruthy();
    expect(screen.getByText(/Barno hozir javob bermayapti/)).toBeTruthy();
    fail = false;
    await act(async () => {
      await fireEvent.press(screen.getByTestId('memory-retry'));
    });
    expect(await screen.findByText('Chilonzor filialida ishlaydi')).toBeTruthy();
  });
});

describe('Settings hub "Ulanishlar" row', () => {
  const HRM = { id: 'hrm', label: 'HRM', configured: true, state: 'connected' as const, login: 'y', enabled: true, expiresAt: null };
  const CRM = { ...HRM, id: 'crm', label: 'CRM', login: null };
  const hubWith = async (connectors: (typeof HRM | typeof CRM)[]) => {
    const { client } = clientWith(memoryServer());
    const services: Services = { ...fakeServices({ chat: fakeChatApi({ connectors: jest.fn(async () => ({ connectors })) }) }), client };
    await render(
      <Providers services={services}>
        <SettingsScreen />
      </Providers>,
    );
    return within(await screen.findByTestId('settings-connections'));
  };

  it('connected but off for chat is a problem here too (the Connections page shows a warn pill)', async () => {
    const row = await hubWith([{ ...HRM, enabled: false }, CRM]);
    expect(await row.findByText("HRM: chatda ishlatish o'chiq")).toBeTruthy();
    expect(row.queryByText(/ulangan$/)).toBeNull();
  });

  it('needing to sign in again wins over "off for chat"', async () => {
    const row = await hubWith([{ ...HRM, enabled: false }, { ...CRM, state: 'expired' as never }]);
    expect(await row.findByText('CRM: qayta kirish kerak')).toBeTruthy();
  });

  it('all connected and on: plain "HRM, CRM ulangan"', async () => {
    const row = await hubWith([HRM, CRM]);
    expect(await row.findByText('HRM, CRM ulangan')).toBeTruthy();
  });
});

describe('Settings hub "Xotira" row', () => {
  it('shows the count ("N ta") and opens /settings/memory', async () => {
    await renderWith(SettingsScreen, memoryServer());
    const row = await screen.findByTestId('settings-memory');
    expect(within(row).getByTestId('icon-Brain')).toBeTruthy();
    await waitFor(() => expect(within(row).getByText('3 ta')).toBeTruthy());
    await fireEvent.press(row);
    expect(router.push).toHaveBeenLastCalledWith('/settings/memory');
  });

  it('"Hali bo\'sh" when nothing is remembered', async () => {
    await renderWith(SettingsScreen, memoryServer([]));
    expect(await within(await screen.findByTestId('settings-memory')).findByText("Hali bo'sh")).toBeTruthy();
  });

  it('no value line when memory cannot be loaded (the page itself explains)', async () => {
    await renderWith(SettingsScreen, memoryServer(ITEMS, { list: () => envelope(503, 'x') }));
    const row = await screen.findByTestId('settings-memory');
    await waitFor(() => expect(within(row).queryByText('...')).toBeNull());
    expect(within(row).getByText('Xotira')).toBeTruthy();
    expect(within(row).queryByText(/ta$/)).toBeNull();
  });
});
