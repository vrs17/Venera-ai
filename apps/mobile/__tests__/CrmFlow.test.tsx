/**
 * "CRMga qo'shish" ekranda (RNTL + expo-router): kutish holati, taklif kartasi
 * (qatorlar, ogohlantirish, qolgan vaqt), tasdiq / bekor / 410 va soat bo'yicha
 * muddati o'tishi, matnli javob, CRM ulanmagan (-> Mini App), saqlangan holatlar
 * qayta ochilganda va "Vazifalarim" ekrani. Tarmoqqa chiqmaydi.
 */
import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { router, Stack } from 'expo-router';
import { renderRouter } from 'expo-router/testing-library';
import type { ReactNode } from 'react';
import { AccessibilityInfo, Linking, Text } from 'react-native';

import { ApiError } from '@/api/client';
import type { ActionCrm, ActionItem, ActionResult, CrmResult, GlobalActionItem } from '@/api/types';
import MyActionItemsScreen from '@/app/action-items';
import { unstable_settings } from '@/app/_layout';
import MeetingRoute from '@/app/meeting/[id]';
import { useCrmStore } from '@/features/crm/crmStore';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeActionsApi, fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { actionItem, crmProposal, crmState, globalItem } from './fixtures/server';

const ID = 'a'.repeat(32);
const IID = 'c'.repeat(32);

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const proposed = (token = 'tok-1', expiresInMs?: number): CrmResult => {
  const p = crmProposal({ token }, expiresInMs);
  return { status: 'proposed', proposal: p, text: null, reason: null, item: { ...actionItem, crm: crmState({}, p) } };
};

/**
 * Serverdagi vazifa holati o'zgaruvchan: `/crm` taklif saqlasa keyingi `GET action-items`
 * uni qaytaradi (haqiqiy server kabi), tasdiq/bekor esa holatni yozadi.
 */
function backend(
  opts: {
    crm?: ActionCrm | null;
    itemStatus?: ActionItem['status'];
    crmReply?: () => Promise<CrmResult> | CrmResult;
    confirm?: (t: string) => Promise<ActionResult>;
    get?: (t: string) => Promise<ActionResult>;
  } = {},
) {
  let current: ActionItem = { ...actionItem, status: opts.itemStatus ?? actionItem.status, crm: opts.crm ?? null };
  const meetings = fakeMeetingsApi({
    actionItems: jest.fn(async () => ({ items: [current] })),
    myActionItems: jest.fn(async () => ({ items: [{ ...current, meetingTitle: globalItem.meetingTitle, recordedAt: globalItem.recordedAt } as GlobalActionItem] })),
    actionItemToCrm: jest.fn(async () => {
      const r = await (opts.crmReply ?? (() => proposed()))();
      if (r.item) current = r.item;
      return r;
    }),
  });
  const actions = fakeActionsApi({
    confirm: jest.fn(
      opts.confirm ??
        (async (token: string) => {
          current = { ...current, crm: current.crm && { ...current.crm, status: 'executed', result: { key: 'DVSIB-231' } } };
          return { token, status: 'executed', ok: true, result: { key: 'DVSIB-231' } };
        }),
    ),
    cancel: jest.fn(async (token: string) => {
      current = { ...current, crm: current.crm && { ...current.crm, status: 'cancelled' } };
      return { token, status: 'cancelled', ok: true };
    }),
    ...(opts.get ? { get: jest.fn(opts.get) } : {}),
  });
  /** Serverning o'zi (javob telefonga yetmasa ham) holatni yozadi. */
  const server = {
    get item() {
      return current;
    },
    set item(v: ActionItem) {
      current = v;
    },
  };
  return { meetings, actions, server };
}

const routes = {
  _layout: { default: () => <Stack />, unstable_settings },
  index: () => <Text>chat-screen</Text>,
  'meeting/[id]': MeetingRoute,
  'action-items': MyActionItemsScreen,
};

async function openMeeting(b: ReturnType<typeof backend>) {
  const services = fakeServices({ meetings: b.meetings, actions: b.actions });
  const wrapper = ({ children }: { children: ReactNode }) => <Providers services={services}>{children}</Providers>;
  await renderRouter(routes, { initialUrl: `/meeting/${ID}`, wrapper });
  await waitFor(() => expect(screen.getByTestId('meeting-title')).toBeTruthy());
  await fireEvent.press(screen.getByTestId('tab-actions'));
  await waitFor(() => expect(screen.getByTestId(`ai-check-${IID}`)).toBeTruthy());
  return b;
}

beforeEach(() => {
  useSettings.setState({ uiLang: 'uz' });
  useCrmStore.getState().reset();
});

describe('Add to CRM - proposal card', () => {
  it('waits with a clear busy state, then shows a readable proposal; confirm -> added with the CRM key', async () => {
    const reply = deferred<CrmResult>();
    const b = await openMeeting(backend({ crmReply: () => reply.promise }));
    const announce = jest.spyOn(AccessibilityInfo, 'announceForAccessibility');
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    expect(screen.getByTestId(`crm-busy-${IID}`)).toBeTruthy();
    expect(screen.getByText('Barno vazifani CRM uchun tayyorlamoqda...')).toBeTruthy();
    // TalkBack bir marta aytadi; soniya hisoblagichi live region emas.
    expect(announce).toHaveBeenCalledTimes(1);
    expect(announce).toHaveBeenCalledWith('Barno vazifani CRM uchun tayyorlamoqda...');
    expect(screen.getByTestId(`crm-busy-${IID}`).props.accessibilityLiveRegion).toBeUndefined();
    expect(screen.queryByTestId(`crm-add-${IID}`)).toBeNull(); // ikkinchi so'rov tugmasi yo'q
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledWith(ID, IID, {});

    await act(async () => reply.resolve(proposed()));
    await waitFor(() => expect(screen.getByTestId(`crm-card-${IID}`)).toBeTruthy());
    expect(screen.getByTestId(`crm-card-${IID}`).props.accessibilityLabel).toBeUndefined(); // matn TalkBack'dan yashirilmaydi
    expect(screen.getByText('CRM · Yangi vazifa taklifi')).toBeTruthy();
    expect(screen.getByText('DVSIB loyihasida yangi vazifa: Hisobotni yuborish')).toBeTruthy();
    for (const label of ['Nomi', 'Loyiha', "Mas'ul", 'Muddat', 'Ustuvorlik']) expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText('Raqamli savdo')).toBeTruthy();
    expect(screen.getByText('Dilnoza Karimova')).toBeTruthy();
    expect(screen.getByText('Oddiy')).toBeTruthy(); // eski qiymat (ustidan chizilgan), CRM "Normal" -> o'zbekcha
    expect(screen.getByText('Yuqori')).toBeTruthy(); // CRM "High"
    expect(screen.queryByText('High')).toBeNull();
    expect(screen.queryByText(/[{}]/)).toBeNull(); // xom JSON yo'q
    expect(screen.getByText(/2 ta odam topildi/)).toBeTruthy();
    expect(screen.getByTestId(`crm-countdown-${IID}`)).toHaveTextContent('15 daq qoldi');
    expect(screen.getByText("Tasdiqlamaguningizcha CRMda hech narsa o'zgarmaydi.")).toBeTruthy();

    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-outcome-${IID}`)).toBeTruthy());
    expect(b.actions.confirm).toHaveBeenCalledWith('tok-1');
    expect(b.actions.confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByText("CRMga qo'shildi")).toBeTruthy();
    expect(screen.getByText('DVSIB-231')).toBeTruthy();
    expect(screen.queryByTestId(`crm-confirm-${IID}`)).toBeNull();
    expect(screen.queryByTestId(`crm-cancel-${IID}`)).toBeNull();
  });

  it('confirm in flight: both buttons settle into a busy state - a second tap does nothing', async () => {
    const conf = deferred<ActionResult>();
    const b = await openMeeting(backend({ crm: crmState(), confirm: () => conf.promise }));
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    expect(screen.getByText('Bajarilmoqda...')).toBeTruthy();
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await fireEvent.press(screen.getByTestId(`crm-cancel-${IID}`));
    expect(b.actions.confirm).toHaveBeenCalledTimes(1);
    expect(b.actions.cancel).not.toHaveBeenCalled();
    await act(async () => conf.resolve({ token: 'tok-1', status: 'executed', ok: true, result: { key: 'DVSIB-231' } }));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
  });

  it('cancel: nothing is written; the item can be sent again (a fresh proposal)', async () => {
    const b = await openMeeting(backend({ crm: crmState(), crmReply: () => proposed('tok-2') }));
    await fireEvent.press(screen.getByTestId(`crm-cancel-${IID}`));
    await waitFor(() => expect(screen.getByText('Taklif rad etildi')).toBeTruthy());
    expect(b.actions.cancel).toHaveBeenCalledWith('tok-1');
    expect(b.actions.confirm).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledWith(ID, IID, { force: true });
    await waitFor(() => expect(screen.getByTestId(`crm-confirm-${IID}`)).toBeTruthy());
  });

  it('expired by 410 on confirm: final state with "Yangi taklif olish" that asks for a new proposal', async () => {
    const b = await openMeeting(
      backend({
        crm: crmState(),
        crmReply: () => proposed('tok-2'),
        confirm: async () => Promise.reject(new ApiError(410, 'expired', 'Taklif muddati tugagan')),
      }),
    );
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText('Taklif muddati tugagan')).toBeTruthy());
    expect(screen.queryByTestId(`crm-confirm-${IID}`)).toBeNull();
    expect(screen.queryByTestId(`crm-error-${IID}`)).toBeNull(); // xato emas - holat
    await fireEvent.press(screen.getByTestId(`crm-resend-${IID}`));
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledWith(ID, IID, { force: true });
    await waitFor(() => expect(screen.getByTestId(`crm-confirm-${IID}`)).toBeTruthy());
    expect(screen.getByTestId(`crm-countdown-${IID}`)).toHaveTextContent('15 daq qoldi');
  });

  it('expired by the countdown on the phone: the card settles by itself', async () => {
    const b = await openMeeting(backend({ crm: crmState({}, crmProposal({}, 1500)) }));
    expect(screen.getByTestId(`crm-countdown-${IID}`)).toHaveTextContent(/^[12] soniya qoldi$/);
    await waitFor(() => expect(screen.getByText('Taklif muddati tugagan')).toBeTruthy(), { timeout: 5000 });
    expect(screen.queryByTestId(`crm-confirm-${IID}`)).toBeNull();
    expect(screen.queryByTestId(`crm-countdown-${IID}`)).toBeNull();
    expect(screen.getByTestId(`crm-resend-${IID}`)).toBeTruthy();
    expect(b.actions.confirm).not.toHaveBeenCalled();
  }, 15_000);

  it('a network error on confirm is shown in the card and the proposal stays confirmable', async () => {
    let fail = true;
    const b = await openMeeting(
      backend({
        crm: crmState(),
        confirm: async (token) => {
          if (fail) throw new ApiError(0, 'network', 'offline');
          return { token, status: 'executed', ok: true, result: { key: 'DVSIB-231' } };
        },
      }),
    );
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-error-${IID}`)).toHaveTextContent("Internet yo'q"));
    fail = false;
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
    expect(b.actions.confirm).toHaveBeenCalledTimes(2);
  });
});

describe('Add to CRM - other answers', () => {
  it('answered: Barno text as markdown-lite (no raw asterisks), close returns to the button', async () => {
    await openMeeting(
      backend({
        crmReply: () => ({ status: 'answered', proposal: null, text: '**Loyiha** aniqlanmadi. Qaysi biri: *DVSIB* yoki *RS*? [S2] mas\'ul.', reason: null, item: null }),
      }),
    );
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-answer-${IID}`)).toBeTruthy());
    expect(screen.getByText('Barno javobi')).toBeTruthy();
    expect(screen.getByText('Loyiha')).toBeTruthy();
    expect(screen.getByText('DVSIB')).toBeTruthy();
    expect(screen.getByText(/2-ishtirokchi mas'ul/)).toBeTruthy(); // [S2] -> spiker nomi (renderTokens)
    expect(screen.queryByText(/\*/)).toBeNull();
    await fireEvent.press(screen.getByTestId(`crm-dismiss-${IID}`));
    expect(screen.getByTestId(`crm-add-${IID}`)).toBeTruthy();
  });

  it('crm_not_connected: explains where to connect CRM and returns to the Mini App', async () => {
    await openMeeting(backend({ crmReply: () => ({ status: 'failed', proposal: null, text: null, reason: 'crm_not_connected', item: null }) }));
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await waitFor(() => expect(screen.getByText('CRM ulanmagan')).toBeTruthy());
    expect(screen.getByText(/Sozlamalar > Ulanishlar/)).toBeTruthy();
    await fireEvent.press(screen.getByTestId(`crm-open-chat-${IID}`));
    await waitFor(() => expect(screen.getByText('chat-screen')).toBeTruthy());
  });

  it('other failures: a friendly message (no raw code) and a retry', async () => {
    let n = 0;
    const b = await openMeeting(
      backend({
        crmReply: () => (++n === 1 ? { status: 'failed', proposal: null, text: null, reason: 'assistant_busy', item: null } : proposed()),
      }),
    );
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await waitFor(() => expect(screen.getByText("Barno hozir band. Bir daqiqadan keyin qayta urinib ko'ring.")).toBeTruthy());
    expect(screen.queryByText(/assistant_busy/)).toBeNull();
    await fireEvent.press(screen.getByTestId(`crm-retry-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-card-${IID}`)).toBeTruthy());
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledTimes(2);
    expect(b.meetings.actionItemToCrm).toHaveBeenLastCalledWith(ID, IID, {}); // force yo'q
  });

  it('transport timeout while waiting -> friendly retry', async () => {
    await openMeeting(backend({ crmReply: () => Promise.reject(new ApiError(0, 'timeout', 'x')) }));
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await waitFor(() => expect(screen.getByText("Barno javobi juda uzoq cho'zildi. Qayta urinib ko'ring.")).toBeTruthy());
  });
});

describe('Add to CRM - lost replies (504 / timeout / network)', () => {
  it('request reply lost but the server stored the proposal: the card appears by itself, v3 is not asked again', async () => {
    const b = backend();
    b.meetings.actionItemToCrm.mockImplementation(async () => {
      b.server.item = { ...actionItem, crm: crmState() };
      throw new ApiError(504, 'gateway_timeout', 'nginx');
    });
    await openMeeting(b);
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-confirm-${IID}`)).toBeTruthy());
    expect(screen.queryByTestId(`crm-failed-${IID}`)).toBeNull();
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledTimes(1);
  });

  it('retry after a lost reply sends no force: the server hands back the stored proposal', async () => {
    let n = 0;
    const b = await openMeeting(
      backend({ crmReply: () => (++n === 1 ? Promise.reject(new ApiError(0, 'timeout', 'x')) : proposed()) }),
    );
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-failed-${IID}`)).toBeTruthy());
    await fireEvent.press(screen.getByTestId(`crm-retry-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-confirm-${IID}`)).toBeTruthy());
    expect(b.meetings.actionItemToCrm).toHaveBeenNthCalledWith(1, ID, IID, {});
    expect(b.meetings.actionItemToCrm).toHaveBeenNthCalledWith(2, ID, IID, {});
  });

  it('confirm reply lost but the task was created: the check shows "added" - no second confirm', async () => {
    const b = backend({
      crm: crmState(),
      confirm: async () => {
        const crm = b.server.item.crm;
        b.server.item = { ...b.server.item, crm: crm && { ...crm, status: 'executed', result: { key: 'DVSIB-231' } } };
        throw new ApiError(0, 'timeout', 'x');
      },
    });
    await openMeeting(b);
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
    expect(screen.getByText('DVSIB-231')).toBeTruthy();
    expect(b.actions.confirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId(`crm-confirm-${IID}`)).toBeNull();
    expect(screen.queryByTestId(`crm-resend-${IID}`)).toBeNull();
  });

  it('confirm reply lost, then the token is gone: "result unknown" (check CRM), never "expired"', async () => {
    let n = 0;
    const b = await openMeeting(
      backend({
        crm: crmState(),
        confirm: async () => {
          if (++n === 1) throw new ApiError(0, 'network', 'offline');
          throw new ApiError(410, 'gone', 'Taklif muddati tugagan');
        },
        get: async () => Promise.reject(new ApiError(404, 'not_found', 'x')),
      }),
    );
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByTestId(`crm-error-${IID}`)).toHaveTextContent("Internet yo'q"));
    expect(screen.getByTestId(`crm-unsure-${IID}`)).toHaveTextContent(/avval natija tekshiriladi/);
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("Natija noma'lum")).toBeTruthy());
    expect(screen.getByTestId(`crm-unknown-${IID}`)).toHaveTextContent(/CRMda tekshiring/);
    expect(screen.queryByText('Taklif muddati tugagan')).toBeNull();
    expect(screen.getByTestId(`crm-resend-${IID}`)).toHaveTextContent('Yangi taklif olish');
    expect(b.actions.confirm).toHaveBeenCalledTimes(2);
    expect(b.actions.get).toHaveBeenCalled();
  });

  it('a reply without a status but ok:true settles by verb (server proposal_outcome)', async () => {
    await openMeeting(backend({ crm: crmState(), confirm: async (token) => ({ token, ok: true, result: { key: 'DVSIB-231' } }) as unknown as ActionResult }));
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
    expect(screen.queryByText("CRMga qo'shib bo'lmadi")).toBeNull();
  });

  it('a reply that says nothing (pending, no ok): the service is asked instead of guessing', async () => {
    const b = await openMeeting(
      backend({
        crm: crmState(),
        confirm: async (token) => ({ token, status: 'pending' }),
        get: async (token) => ({ token, status: 'executed', ok: true, result: { key: 'DVSIB-231' } }),
      }),
    );
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
    expect(b.actions.get).toHaveBeenCalledWith('tok-1');
    expect(b.actions.confirm).toHaveBeenCalledTimes(1);
  });

  it('a CRM rejection shows a translated line first and the platform text only as a muted detail', async () => {
    await openMeeting(
      backend({ crm: crmState(), confirm: async (token) => ({ token, status: 'failed', ok: false, error: 'Field customfield_10020 is required' }) }),
    );
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shib bo'lmadi")).toBeTruthy());
    expect(screen.getByText("CRM o'zgarishni qabul qilmadi. Yangi taklif olib, qayta urinib ko'ring.")).toBeTruthy();
    expect(screen.getByText('CRM javobi: Field customfield_10020 is required')).toBeTruthy();
  });
});

describe('Add to CRM - persisted state and leaving the screen', () => {
  it('leaving while v3 works is safe: the proposal is there when the meeting is reopened', async () => {
    const reply = deferred<CrmResult>();
    const b = await openMeeting(backend({ crmReply: () => reply.promise }));
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await act(async () => router.back());
    await waitFor(() => expect(screen.getByText('chat-screen')).toBeTruthy());
    await act(async () => reply.resolve(proposed()));
    await act(async () => router.push(`/meeting/${ID}`));
    await waitFor(() => expect(screen.getByTestId('tab-actions')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('tab-actions'));
    await waitFor(() => expect(screen.getByTestId(`crm-confirm-${IID}`)).toBeTruthy());
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledTimes(1);
  });

  it('reopening while v3 still works shows the busy state (no second request)', async () => {
    const reply = deferred<CrmResult>();
    const b = await openMeeting(backend({ crmReply: () => reply.promise }));
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    await act(async () => router.back());
    await act(async () => router.push(`/meeting/${ID}`));
    await waitFor(() => expect(screen.getByTestId('tab-actions')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('tab-actions'));
    await waitFor(() => expect(screen.getByTestId(`crm-busy-${IID}`)).toBeTruthy());
    await act(async () => reply.resolve(proposed()));
    await waitFor(() => expect(screen.getByTestId(`crm-card-${IID}`)).toBeTruthy());
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledTimes(1);
  });

  it('a stored pending proposal is still confirmable', async () => {
    const b = await openMeeting(backend({ crm: crmState({}, crmProposal({}, 9 * 60_000)) }));
    expect(screen.getByTestId(`crm-countdown-${IID}`)).toHaveTextContent('9 daq qoldi');
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
    expect(b.actions.confirm).toHaveBeenCalledWith('tok-1');
  });

  it('a stored added item shows as added (key + link), without buttons', async () => {
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
    await openMeeting(backend({ crm: crmState({ status: 'executed', result: { key: 'DVSIB-231', url: 'https://crm.brb-tech.uz/browse/DVSIB-231' } }) }));
    expect(screen.getByTestId(`crm-added-${IID}`)).toBeTruthy();
    expect(screen.getByText("✓ CRMga qo'shilgan · DVSIB-231")).toBeTruthy();
    expect(screen.queryByTestId(`crm-add-${IID}`)).toBeNull();
    expect(screen.queryByTestId(`crm-confirm-${IID}`)).toBeNull();
    await fireEvent.press(screen.getByTestId(`crm-link-${IID}`));
    await waitFor(() => expect(open).toHaveBeenCalledWith('https://crm.brb-tech.uz/browse/DVSIB-231'));
  });

  it('a stored expired proposal is final with "Yangi taklif olish"', async () => {
    await openMeeting(backend({ crm: crmState({ status: 'expired' }) }));
    expect(screen.getByText('Taklif muddati tugagan')).toBeTruthy();
    expect(screen.getByTestId(`crm-resend-${IID}`)).toBeTruthy();
    expect(screen.queryByTestId(`crm-confirm-${IID}`)).toBeNull();
  });

  it('a stored cancelled proposal offers the button again (with a note)', async () => {
    const b = await openMeeting(backend({ crm: crmState({ status: 'cancelled' }) }));
    expect(screen.getByText('Taklif rad etildi')).toBeTruthy();
    expect(screen.queryByTestId(`crm-card-${IID}`)).toBeNull();
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledWith(ID, IID, { force: true });
  });

  it('dismissed items without CRM state hide the button', async () => {
    await openMeeting(backend({ itemStatus: 'dismissed' }));
    expect(screen.queryByTestId(`crm-add-${IID}`)).toBeNull();
  });
});

describe('Add to CRM - "My tasks" screen and languages', () => {
  it('works from the cross-meeting list too', async () => {
    const b = backend({ crm: null });
    const services = fakeServices({ meetings: b.meetings, actions: b.actions });
    const wrapper = ({ children }: { children: ReactNode }) => <Providers services={services}>{children}</Providers>;
    await renderRouter(routes, { initialUrl: '/action-items', wrapper });
    await waitFor(() => expect(screen.getByTestId(`crm-add-${IID}`)).toBeTruthy());
    await fireEvent.press(screen.getByTestId(`crm-add-${IID}`));
    expect(b.meetings.actionItemToCrm).toHaveBeenCalledWith(ID, IID, {});
    await waitFor(() => expect(screen.getByTestId(`crm-confirm-${IID}`)).toBeTruthy());
    await fireEvent.press(screen.getByTestId(`crm-confirm-${IID}`));
    await waitFor(() => expect(screen.getByText("CRMga qo'shildi")).toBeTruthy());
  });

  it('Russian and English labels', async () => {
    useSettings.setState({ uiLang: 'ru' });
    await openMeeting(backend({ crm: crmState() }));
    expect(screen.getByText('Подтвердить')).toBeTruthy();
    expect(screen.getByText('Отклонить')).toBeTruthy();
    expect(screen.getByText('Ответственный')).toBeTruthy();
    await act(async () => useSettings.setState({ uiLang: 'en' }));
    expect(screen.getByText('Confirm')).toBeTruthy();
    expect(screen.getByText('Assignee')).toBeTruthy();
  });
});
