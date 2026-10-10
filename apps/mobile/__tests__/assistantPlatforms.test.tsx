/**
 * Barno MANBALARI (yordamchi 3.3, web/Mini App bilan bir qoida):
 *  - platformalar ro'yxati (7 ta: belgi, nom, vazifa; uz/ru/en) va tartib;
 *  - jonli so'rov nomi `lookupTitle` ("CRM · Vazifa ma'lumoti", xom asbob nomi HECH QACHON) va
 *    5 ta yangi tur (DWH, Biznes 24/7, Superapp, qo'llanmalar, Biznes Help) belgilari;
 *  - manbalar oynasi va "N manba" tugmasidagi belgilar;
 *  - Ulanishlar > "Manbalar": optimistik kalit va xatoda qaytarish, HRM/CRM login muammosi
 *    qatori va "Yoqish" (bizning token kaliti), platformani yoqish token kalitini ham yoqadi.
 * Tarmoq yo'q: soxta fetch.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { readFileSync } from 'fs';
import { join } from 'path';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { createAssistantApi, toPlatform, type Platform } from '@/api/assistant';
import type { AnswerSource, ChatFrame, ConnectorStatus } from '@/api/chat';
import { ApiClient } from '@/api/client';
import ChatScreen from '@/app/index';
import ConnectionsScreen from '@/app/settings/connections';
import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import { useChats } from '@/features/chat/chatsStore';
import {
  isGuideSource,
  isLookupSource,
  loginIssue,
  lookupTitle,
  orderPlatforms,
  PLATFORM_IDS,
  platformName,
  platformOfSource,
  platformPurpose,
  toolKey,
} from '@/features/chat/platforms';
import { usePro } from '@/features/chat/proStore';
import { sourceKind, sourceMarks, sourceMeta, sourceTitle } from '@/features/chat/sources';
import { SourcesSheet } from '@/features/chat/ui/Sheets';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { DICTS, makeT, UI_LANGS } from '@/i18n';
import type { Services } from '@/services';
import { showToast } from '@/ui/errors';

import { envelope, fakeFetch, type FakeReply, type FakeRequest, type Handler } from './fixtures/fakeFetch';
import { fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => ({ router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn() } }));
jest.mock('@/ui/errors', () => ({ ...jest.requireActual('@/ui/errors'), showToast: jest.fn() }));

const t = makeT('uz');
const metrics = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 24, left: 0, right: 0, bottom: 16 } };

const P = (id: string, over: Partial<Platform> = {}): Platform => ({
  id,
  name: id.toUpperCase(),
  description: '',
  kind: 'live',
  needs_login: id === 'hrm' || id === 'crm',
  available: true,
  user_enabled: true,
  enabled: true,
  ...over,
});

const HRM: ConnectorStatus = { id: 'hrm', label: 'HRM', configured: true, state: 'connected', login: 'ymamajonov', enabled: true, expiresAt: null };
const CRM: ConnectorStatus = { id: 'crm', label: 'CRM', configured: true, state: 'connected', login: null, enabled: true, expiresAt: null };

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', proOn: false, themePref: 'light' });
});

describe('platform registry', () => {
  it('7 platforms, each with a name and a one-line purpose in uz/ru/en (uz has no Cyrillic)', () => {
    expect(PLATFORM_IDS).toEqual(['hrm', 'crm', 'dwh', 'biznes247', 'superapp', 'biznes247_kb', 'biznes247_help']);
    for (const lang of UI_LANGS) {
      const tl = makeT(lang);
      for (const id of PLATFORM_IDS) {
        expect([lang, id, platformName(id, tl)]).toEqual([lang, id, expect.not.stringMatching(/^set\./)]);
        expect([lang, id, platformPurpose(id, tl)]).toEqual([lang, id, expect.not.stringMatching(/^set\.|^$/)]);
      }
    }
    expect(PLATFORM_IDS.map((id) => platformName(id, t))).toEqual(['HRM', 'CRM', 'DWH', 'Biznes 24/7', 'Superapp', "Biznes 24/7 qo'llanmalari", 'Biznes Help']);
    expect(platformName('biznes247_kb', makeT('ru'))).toBe('Руководства Biznes 24/7');
    // Notanish platforma - xizmat nomi / izohi bilan (bo'sh emas), nomi bo'lmasa id katta harfda.
    expect(platformName('newsys', t, 'Yangi tizim')).toBe('Yangi tizim');
    expect(platformName('newsys', t)).toBe('NEWSYS');
    expect(platformPurpose('newsys', t, 'Izoh')).toBe('Izoh');
  });

  it('order follows the registry; unknown ones go last in server order', () => {
    expect(orderPlatforms([P('zeta'), P('superapp'), P('hrm'), P('alpha'), P('crm')]).map((p) => p.id)).toEqual(['hrm', 'crm', 'superapp', 'zeta', 'alpha']);
  });

  it('tool names: every known tool is translated in all languages; unknown tools have no key', () => {
    const tools = Object.keys(DICTS.uz).filter((k) => k.startsWith('set.tool.'));
    expect(tools.length).toBe(20);
    for (const lang of UI_LANGS) for (const k of tools) expect((DICTS[lang] as Record<string, string>)[k]).toBeTruthy();
    expect(toolKey('crm_issue_get')).toBe('set.tool.crm_issue_get');
    expect(toolKey('dwh_branch_kpi')).toBeNull();
  });

  it('login issue: only for an enabled login platform with a configured connector', () => {
    const hrm = { id: 'hrm', needs_login: true, enabled: true };
    expect(loginIssue(hrm, HRM)).toBeNull();
    expect(loginIssue(hrm, { ...HRM, enabled: false })).toBe('offForChat');
    expect(loginIssue(hrm, { ...HRM, state: 'expired' })).toBe('missing');
    expect(loginIssue(hrm, { ...HRM, state: 'disconnected', enabled: false })).toBe('missing');
    expect(loginIssue({ ...hrm, enabled: false }, { ...HRM, state: 'expired' })).toBeNull();
    expect(loginIssue({ ...hrm, needs_login: false }, { ...HRM, state: 'expired' })).toBeNull();
    expect(loginIssue(hrm, { ...HRM, configured: false, state: 'disconnected' })).toBeNull();
    expect(loginIssue(hrm, null)).toBeNull();
  });

  it('toPlatform: tolerant shape, enabled = available && user_enabled when missing', () => {
    expect(toPlatform({ id: ' DWH ', userEnabled: false, available: true })).toMatchObject({ id: 'dwh', name: ' DWH ', user_enabled: false, enabled: false });
    expect(toPlatform({ id: 'crm', needsLogin: true, available: false })).toMatchObject({ needs_login: true, available: false, user_enabled: true, enabled: false });
    expect(toPlatform({ name: 'no id' })).toBeNull();
  });
});

describe('source titles and icons (5 new kinds)', () => {
  const S = (s: AnswerSource) => s;

  it('lookup title: translated tool -> "Platform · tool"; untranslated -> platform only (never a raw slug)', () => {
    expect(lookupTitle(S({ kind: 'crm', tool: 'crm_issue_get' }), t)).toBe("CRM · Vazifa ma'lumoti");
    expect(lookupTitle(S({ kind: 'hrm', tool: 'hrm_today_late' }), makeT('ru'))).toBe('HRM · Опоздание сегодня');
    expect(lookupTitle(S({ kind: 'dwh', tool: 'dwh_branch_kpi' }), t)).toBe('DWH');
    expect(lookupTitle(S({ kind: 'biznes247', tool: 'biznes247_kpi' }), t)).toBe('Biznes 24/7');
    expect(lookupTitle(S({ kind: 'superapp', tool: 'superapp_users' }), t)).toBe('Superapp');
    // Qo'llanmadan raqamsiz so'rov: maqola nomi odam tilida.
    expect(lookupTitle(S({ kind: 'biznes247_kb', title: 'Karta ochish' }), t)).toBe("Biznes 24/7 qo'llanmalari · Karta ochish");
    expect(lookupTitle(S({ kind: 'biznes247_help' }), makeT('en'))).toBe('Biznes Help');
    // `kind` yo'q - asbob prefiksidan (eng uzun mos): `biznes247_kb_search` -> qo'llanmalar, `biznes247` emas.
    expect(platformOfSource(S({ tool: 'biznes247_kb_search' }))).toBe('biznes247_kb');
    expect(lookupTitle(S({ tool: 'biznes247_kb_search' }), t)).toBe("Biznes 24/7 qo'llanmalari");
    expect(lookupTitle(S({ kind: 'erp', tool: 'erp_x' }), t)).toBe('ERP');
    for (const s of [{ kind: 'dwh', tool: 'dwh_branch_kpi' }, { kind: 'biznes247', tool: 'biznes247_kpi' }]) {
      expect(lookupTitle(s, t)).not.toMatch(/kpi|_/i);
    }
  });

  it('kinds: live platforms are lookups; guides with [n] are citations, without - lookups', () => {
    expect(['dwh', 'biznes247', 'superapp', 'hrm', 'crm'].map((kind) => isLookupSource({ kind }))).toEqual([true, true, true, true, true]);
    expect(isLookupSource({ kind: 'biznes247_kb' })).toBe(true);
    expect(isLookupSource({ kind: 'biznes247_kb', citation_index: 2 })).toBe(false);
    expect(isGuideSource({ kind: 'biznes247_help', citation_index: 2 })).toBe(true);
    expect(sourceKind({ kind: 'biznes247_help', citation_index: 2 })).toBe('guide');
    expect(sourceKind({ kind: 'superapp', marker: 'T3' })).toBe('lookup');
    expect(sourceKind({ kind: 'law', citation_index: 1 })).toBe('law');
    expect(sourceKind({ kind: 'doc', doc_id: 'd1', citation_index: 1 })).toBe('doc');
    expect(sourceTitle({ kind: 'biznes247_kb', citation_index: 1, title: 'Hisob ochish' }, t)).toBe('Hisob ochish');
    expect(sourceMeta({ kind: 'biznes247_kb', citation_index: 1 }, t)).toBe("Biznes 24/7 qo'llanmalari");
    expect(sourceMeta({ kind: 'dwh' }, t)).toBe('');
    expect(sourceMeta({ kind: 'erp', tool: 'erp_x' }, t)).toBe("Tizim ma'lumoti");
  });

  it('marks: platform icon per source, de-duplicated, at most three', () => {
    const marks = sourceMarks([{ kind: 'hrm' }, { kind: 'hrm', tool: 'hrm_schedule' }, { kind: 'dwh' }, { kind: 'superapp' }, { kind: 'biznes247' }]);
    expect(marks.map((m) => m.key)).toEqual(['hrm', 'dwh', 'superapp']);
    expect(sourceMarks([{ kind: 'doc', doc_id: 'd', citation_index: 1 }, { kind: 'law', citation_index: 2 }]).map((m) => m.key)).toEqual(['doc', 'law']);
  });

  it('sources sheet: platform icons, human titles, no "T1"; a guide opens its https link', async () => {
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
    const sources: AnswerSource[] = [
      { kind: 'dwh', tool: 'dwh_branch_kpi', marker: 'T1', digest: 'Filiallar KPI: 12 ta' },
      { kind: 'biznes247', tool: 'biznes247_kpi', marker: 'T2' },
      { kind: 'superapp', tool: 'superapp_users', marker: 'T3' },
      { kind: 'biznes247_kb', citation_index: 1, title: 'Karta ochish', url: 'https://kb.example.uz/karta' },
      { kind: 'biznes247_help', citation_index: 2, title: 'Yordam', url: 'javascript:alert(1)' },
      { kind: 'crm', tool: 'crm_issue_get', marker: 'T4' },
    ];
    await render(
      <SafeAreaProvider initialMetrics={metrics}>
        <SourcesSheet visible onClose={() => {}} sources={sources} api={fakeChatApi()} />
      </SafeAreaProvider>,
    );
    const row = (i: number) => within(screen.getByTestId(`source-${i}`));
    expect(row(0).getByTestId('icon-Database')).toBeTruthy();
    expect(row(0).getByText('DWH')).toBeTruthy();
    expect(row(0).getByText('Filiallar KPI: 12 ta')).toBeTruthy();
    expect(row(1).getByTestId('icon-BriefcaseBusiness')).toBeTruthy();
    expect(row(2).getByTestId('icon-Smartphone')).toBeTruthy();
    expect(row(3).getByTestId('icon-BookOpenText')).toBeTruthy();
    expect(row(3).getByText("Biznes 24/7 qo'llanmalari")).toBeTruthy();
    expect(row(4).getByTestId('icon-LifeBuoy')).toBeTruthy();
    expect(row(5).getByTestId('icon-SquareKanban')).toBeTruthy();
    expect(row(5).getByText("CRM · Vazifa ma'lumoti")).toBeTruthy();
    // "T1" odamga hech narsa demaydi - faqat iqtibos raqami `[1]`.
    expect(screen.queryByText(/T\d/)).toBeNull();
    expect(screen.getByText('[1] ')).toBeTruthy();
    // Xom asbob nomi yo'q.
    expect(screen.queryByText(/Branch kpi|dwh_branch_kpi|biznes247_kpi|superapp_users/i)).toBeNull();

    await act(async () => {
      await fireEvent.press(screen.getByTestId('source-3'));
    });
    expect(open).toHaveBeenCalledWith('https://kb.example.uz/karta');
    // `javascript:` havola - bosilmaydi.
    expect(screen.getByTestId('source-4')).toBeDisabled();
    expect(screen.getByTestId('source-0')).toBeDisabled();
    open.mockRestore();
  });

  it('"N manba" button under an answer shows the platforms the answer came from', async () => {
    useChat.getState().newChat();
    useChats.getState().reset();
    usePro.getState().reset();
    useAuth.getState().setSignedIn({ actorId: 7, actorType: 'EMPLOYEE', email: 'y@x.uz', fullName: 'Yusuf', position: null, department: null, roles: [], passwordChangeRequired: false });
    useAuth.getState().setConfig(null);
    useRecorderStore.setState({ machine: initialRecorderState });
    const stream = jest.fn(async (_q: string, onFrame: (f: ChatFrame) => void) => {
      for (const f of [
        { type: 'sources', items: [{ kind: 'dwh', tool: 'dwh_branch_kpi', marker: 'T1' }, { kind: 'biznes247', tool: 'biznes247_kpi', marker: 'T2' }] },
        { type: 'token', text: 'Filiallar KPI yaxshi [T1][T2].\n\nManba: DWH, Biznes 24/7' },
        { type: 'done', engine: 'v3' },
      ] as ChatFrame[])
        onFrame(f);
    });
    await render(
      <SafeAreaProvider initialMetrics={metrics}>
        <Providers services={fakeServices({ chat: fakeChatApi({ stream }) })}>
          <ChatScreen />
        </Providers>
      </SafeAreaProvider>,
    );
    await fireEvent.changeText(await screen.findByTestId('composer-input'), 'KPI qanday?');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-send'));
    });
    const btn = await screen.findByTestId('answer-sources');
    expect(within(btn).getByText('2 manba')).toBeTruthy();
    expect(within(btn).getByTestId('icon-Database')).toBeTruthy();
    expect(within(btn).getByTestId('icon-BriefcaseBusiness')).toBeTruthy();
    expect(within(btn).queryByTestId('icon-BookOpen')).toBeNull();
    // "Manba: ..." oxirgi qatori - kichik izoh (tugmani takrorlaydi).
    expect(screen.getByTestId('answer-source')).toBeTruthy();
  });
});

// --- Ulanishlar > Manbalar --------------------------------------------------------

function server(opts: { platforms?: unknown[]; connectors?: ConnectorStatus[]; put?: (req: FakeRequest) => FakeReply | Promise<FakeReply>; patch?: (req: FakeRequest) => FakeReply } = {}) {
  let platforms = (opts.platforms ?? PLATFORM_IDS.map((id) => P(id))) as Platform[];
  const handler: Handler = async (req) => {
    if (req.path === '/api/v1/assistant/platforms' && req.method === 'GET') return { json: { platforms } };
    const m = /^\/api\/v1\/assistant\/platforms\/(.+)$/.exec(req.path);
    if (m && req.method === 'PUT') {
      if (opts.put) return opts.put(req);
      const enabled = (req.body as { enabled: boolean }).enabled;
      platforms = platforms.map((p) => (p.id === m[1] ? { ...p, user_enabled: enabled, enabled: enabled && p.available } : p));
      return { json: platforms.find((p) => p.id === m[1]) };
    }
    const c = /^\/api\/v1\/connectors\/(.+)$/.exec(req.path);
    if (c && req.method === 'PATCH') {
      if (opts.patch) return opts.patch(req);
      const base = (opts.connectors ?? []).find((x) => x.id === c[1]);
      return { json: { ...base, enabled: (req.body as { enabled: boolean }).enabled } };
    }
    return envelope(404, 'yo\'q');
  };
  return handler;
}

async function renderConnections(handler: Handler, connectors: ConnectorStatus[] = [HRM, CRM]) {
  const { fetch, calls } = fakeFetch(handler);
  const client = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: { getToken: async () => 'jwt', refreshToken: async () => 'jwt2' } });
  const chat = fakeChatApi({ connectors: jest.fn(async () => ({ connectors })) });
  const services: Services = { ...fakeServices({ chat }), client };
  await render(
    <Providers services={services}>
      <ConnectionsScreen />
    </Providers>,
  );
  return { calls, chat };
}

const sw = (id: string) => screen.getByTestId(`platform-${id}-switch`);

describe('Connections > Sources', () => {
  it('lists the 7 platforms in registry order: icon, name, purpose; the explanation comes first', async () => {
    const reversed = [...PLATFORM_IDS].reverse().map((id) => P(id, { available: id !== 'superapp' }));
    await renderConnections(server({ platforms: reversed }));
    await screen.findByTestId('platform-hrm');
    const section = screen.getByTestId('platforms');
    expect(within(section).getByText('Manbalar')).toBeTruthy();
    expect(within(section).getByText(/shu manbalardan foydalanadi/)).toBeTruthy();
    const rows = within(section).getAllByTestId(/^platform-[a-z0-9_]+$/);
    expect(rows.map((r) => r.props.testID)).toEqual(PLATFORM_IDS.map((id) => `platform-${id}`));
    expect(within(screen.getByTestId('platform-hrm')).getByTestId('icon-Users')).toBeTruthy();
    expect(within(screen.getByTestId('platform-crm')).getByTestId('icon-SquareKanban')).toBeTruthy();
    expect(within(screen.getByTestId('platform-dwh')).getByTestId('icon-Database')).toBeTruthy();
    expect(within(screen.getByTestId('platform-biznes247_help')).getByTestId('icon-LifeBuoy')).toBeTruthy();
    // Izoh 360 dp telefonda bir qatorga sig'maydi - 3 qatorgacha (kesilib "..." bo'lmasin).
    const dwhPurpose = within(screen.getByTestId('platform-dwh')).getByText("Bankning ma'lumotlar ombori: ko'rsatkichlar va hisobotlar");
    expect(dwhPurpose.props.numberOfLines).toBe(3);
    // Server o'chirgan platforma: kulrang, kalit bosilmaydi, sababi OLDINDA yozilgan.
    expect(within(screen.getByTestId('platform-superapp')).getByText("Hozircha mavjud emas · Mijozlar mobil ilovasi ko'rsatkichlari")).toBeTruthy();
    // "Tizimga kirish" bo'limida ham HRM/CRM belgilari "Manbalar"dagi bilan bir xil.
    expect(within(screen.getByTestId('conn-hrm')).getByTestId('icon-Users')).toBeTruthy();
    expect(within(screen.getByTestId('conn-crm')).getByTestId('icon-SquareKanban')).toBeTruthy();
    expect(sw('superapp')).toBeDisabled();
    expect(sw('superapp').props.on).toBe(false);
    expect(sw('dwh').props.on).toBe(true);
  });

  it('toggle is optimistic: flips at once, sends only {enabled}, and stays after the save', async () => {
    let release: (r: FakeReply) => void = () => {};
    const { calls } = await renderConnections(
      server({
        put: (req) =>
          new Promise<FakeReply>((resolve) => {
            release = resolve;
            void req;
          }),
      }),
    );
    await screen.findByTestId('platform-dwh');
    await act(async () => {
      await fireEvent(sw('dwh'), 'valueChange', false);
    });
    // Javob kelmasdan - allaqachon o'chiq, va javob kelguncha qayta bosib bo'lmaydi.
    expect(sw('dwh').props.on).toBe(false);
    expect(sw('dwh')).toBeDisabled();
    const put = calls.find((c) => c.method === 'PUT');
    expect(put).toMatchObject({ path: '/api/v1/assistant/platforms/dwh', body: { enabled: false } });
    await act(async () => {
      release({ json: P('dwh', { user_enabled: false, enabled: false }) });
    });
    await waitFor(() => expect(sw('dwh')).not.toBeDisabled());
    expect(sw('dwh').props.on).toBe(false);
    expect(showToast).not.toHaveBeenCalled();
  });

  it('toggle rolls back and says so when the server refuses', async () => {
    await renderConnections(server({ put: () => envelope(503, 'band', { code: 'upstream_unavailable' }) }));
    await screen.findByTestId('platform-biznes247');
    await act(async () => {
      await fireEvent(sw('biznes247'), 'valueChange', false);
    });
    await waitFor(() => expect(sw('biznes247').props.on).toBe(true));
    expect(sw('biznes247')).not.toBeDisabled();
    expect(showToast).toHaveBeenCalledWith("Biznes 24/7: o'zgartirib bo'lmadi. Qayta urinib ko'ring.");
  });

  it('HRM connected but off for chat: a warning line under HRM with "Yoqish" that turns our token switch on', async () => {
    const { calls } = await renderConnections(server({ connectors: [{ ...HRM, enabled: false }, CRM] }), [{ ...HRM, enabled: false }, CRM]);
    const issue = await screen.findByTestId('platform-hrm-issue');
    expect(within(issue).getByText("Chatda ishlatish o'chiq")).toBeTruthy();
    expect(within(issue).getByTestId('icon-CircleAlert')).toBeTruthy();
    // Hisoblar bo'limidagi holat ham "Ulangan" (yashil) emas - chalg'itmaydi.
    expect(screen.getByTestId('conn-hrm-status').props.children).toBe("Chatda ishlatish o'chiq");
    expect(screen.queryByTestId('platform-crm-issue')).toBeNull();
    // TalkBack "Yoqish" ni qaysi platforma uchunligi bilan o'qiydi.
    expect(screen.getByTestId('platform-hrm-turn-on').props.accessibilityLabel).toBe('HRM: Yoqish');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('platform-hrm-turn-on'));
    });
    expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({ path: '/api/v1/connectors/hrm', body: { enabled: true } });
    await waitFor(() => expect(screen.queryByTestId('platform-hrm-issue')).toBeNull());
    expect(screen.getByTestId('conn-hrm-status').props.children).toBe('Ulangan');
  });

  it('CRM expired: "Hisob ulanmagan" without a fix button; a platform switched off has no warning', async () => {
    const crmExpired = { ...CRM, state: 'expired' as const };
    await renderConnections(server({ platforms: PLATFORM_IDS.map((id) => P(id, id === 'hrm' ? { user_enabled: false, enabled: false } : {})) }), [
      { ...HRM, state: 'expired' },
      crmExpired,
    ]);
    const issue = await screen.findByTestId('platform-crm-issue');
    expect(within(issue).getByText('Hisob ulanmagan')).toBeTruthy();
    expect(screen.queryByTestId('platform-crm-turn-on')).toBeNull();
    // HRM o'chirilgan - Barno undan foydalanmaydi, ogohlantirish kerak emas.
    expect(screen.queryByTestId('platform-hrm-issue')).toBeNull();
  });

  it('turning a login platform ON also turns our "use in chat" token switch on', async () => {
    const off = { ...HRM, enabled: false };
    const { calls } = await renderConnections(
      server({ platforms: PLATFORM_IDS.map((id) => P(id, id === 'hrm' ? { user_enabled: false, enabled: false } : {})), connectors: [off, CRM] }),
      [off, CRM],
    );
    await screen.findByTestId('platform-hrm');
    expect(sw('hrm').props.on).toBe(false);
    await act(async () => {
      await fireEvent(sw('hrm'), 'valueChange', true);
    });
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.path, c.body])).toEqual([
      ['PUT', '/api/v1/assistant/platforms/hrm', { enabled: true }],
      ['PATCH', '/api/v1/connectors/hrm', { enabled: true }],
    ]);
    await waitFor(() => expect(screen.getByTestId('conn-hrm-status').props.children).toBe('Ulangan'));
    expect(sw('hrm').props.on).toBe(true);
    expect(screen.queryByTestId('platform-hrm-issue')).toBeNull();
  });

  it('platform saved but the chat token could not be enabled: the switch stays on and the toast says exactly that', async () => {
    const off = { ...HRM, enabled: false };
    const { calls } = await renderConnections(
      server({
        platforms: PLATFORM_IDS.map((id) => P(id, id === 'hrm' ? { user_enabled: false, enabled: false } : {})),
        connectors: [off, CRM],
        patch: () => envelope(503, 'band'),
      }),
      [off, CRM],
    );
    await screen.findByTestId('platform-hrm');
    await act(async () => {
      await fireEvent(sw('hrm'), 'valueChange', true);
    });
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("HRM yoqildi, lekin chatda ishlatishni yoqib bo'lmadi. «Yoqish»ni bosing."));
    expect(showToast).not.toHaveBeenCalledWith(expect.stringContaining("o'zgartirib bo'lmadi"));
    expect(sw('hrm').props.on).toBe(true);
    // Ogohlantirish qatori va "Yoqish" - qayta urinish yo'li ko'z oldida.
    expect(screen.getByTestId('platform-hrm-turn-on')).toBeTruthy();
  });

  it('switching HRM on and tapping "Yoqish" at the same moment sends ONE token PATCH', async () => {
    const off = { ...HRM, enabled: false };
    let releasePut: () => void = () => {};
    let releasePatch: () => void = () => {};
    const base = server({ platforms: PLATFORM_IDS.map((id) => P(id, id === 'hrm' ? { user_enabled: false, enabled: false } : {})), connectors: [off, CRM] });
    const { calls } = await renderConnections(async (req) => {
      if (req.method === 'PUT') await new Promise<void>((r) => (releasePut = r));
      if (req.method === 'PATCH') await new Promise<void>((r) => (releasePatch = r));
      return base(req);
    }, [off, CRM]);
    await screen.findByTestId('platform-hrm');
    await act(async () => {
      await fireEvent(sw('hrm'), 'valueChange', true);
    });
    // Optimistik yoqildi - token kaliti o'chiq, "Yoqish" darhol ko'rinadi va bosiladi (PUT hali kelmagan).
    await act(async () => {
      await fireEvent.press(await screen.findByTestId('platform-hrm-turn-on'));
    });
    await waitFor(() => expect(calls.filter((c) => c.method !== 'GET').map((c) => c.method)).toEqual(['PUT', 'PATCH']));
    // PUT keldi - kalit o'zi ham token kalitini yoqmoqchi bo'ladi, lekin "Yoqish" so'rovi hali yo'lda.
    await act(async () => {
      releasePut();
    });
    await waitFor(() => expect(sw('hrm')).not.toBeDisabled());
    await act(async () => {
      releasePatch();
    });
    await waitFor(() => expect(screen.getByTestId('conn-hrm-status').props.children).toBe('Ulangan'));
    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1);
    expect(showToast).not.toHaveBeenCalled();
  });

  it('load error -> retry', async () => {
    let fail = true;
    const base = server();
    await renderConnections((req) => (fail && req.path === '/api/v1/assistant/platforms' ? envelope(502, 'x', { code: 'upstream_error' }) : base(req)));
    expect(await screen.findByText("Manbalarni yuklab bo'lmadi")).toBeTruthy();
    fail = false;
    await act(async () => {
      await fireEvent.press(screen.getByTestId('platforms-retry'));
    });
    expect(await screen.findByTestId('platform-hrm')).toBeTruthy();
  });

  it('empty platform list is not an error', async () => {
    await renderConnections(server({ platforms: [] }));
    expect(await screen.findByText("Hozircha sozlanadigan manba yo'q")).toBeTruthy();
  });

  it('platforms API: accepts the upstream `connectors` list key and PUTs exactly {enabled}', async () => {
    const { fetch, calls } = fakeFetch((req) => (req.method === 'GET' ? { json: { connectors: [{ id: 'hrm' }, { bad: 1 }] } } : { json: { id: 'hrm', user_enabled: false } }));
    const api = createAssistantApi(new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: { getToken: async () => 'jwt', refreshToken: async () => 'jwt' } }));
    expect((await api.listPlatforms()).map((p) => p.id)).toEqual(['hrm']);
    expect(await api.setPlatform('hrm', false)).toMatchObject({ id: 'hrm', user_enabled: false, enabled: false });
    expect(calls[1]).toMatchObject({ method: 'PUT', path: '/api/v1/assistant/platforms/hrm', body: { enabled: false } });
  });
});

describe('route', () => {
  it('settings/memory is registered inside the signed-in guard', () => {
    const layout = readFileSync(join(__dirname, '../src/app/_layout.tsx'), 'utf8');
    const start = layout.indexOf('<Stack.Protected guard={signedIn}>');
    const block = layout.slice(start, layout.indexOf('</Stack.Protected>', start));
    expect(block).toContain('<Stack.Screen name="settings/memory"');
  });
});
