/**
 * Vazifa -> CRM: API o'ramalari (yo'l, metod, tana, uzun timeout) va jarayon
 * (`crmStore`): taklif keshga yoziladi, ikki marta bosish bitta so'rov, tasdiq /
 * bekor / 404-410 muddati o'tgan, tarmoq xatosi kartani tasdiqlanadigan qoldiradi.
 * Tarmoqqa chiqmaydi.
 */
import { QueryClient } from '@tanstack/react-query';

import { createActionsApi, isExpiredError } from '@/api/actions';
import { ACTION_TIMEOUT_MS, AI_TIMEOUT_MS, ApiClient, ApiError, type FetchLike, type TokenProvider } from '@/api/client';
import { createMeetingsApi } from '@/api/meetings';
import type { ActionItem, CrmResult, GlobalActionItem } from '@/api/types';
import { createCrmController, useCrmStore } from '@/features/crm/crmStore';
import { qk } from '@/features/meeting/queries';

import { envelope, fakeFetch, type FakeReply } from './fixtures/fakeFetch';
import { actionItem, crmProposal, crmState, globalItem } from './fixtures/server';

const tp: TokenProvider = { getToken: async () => 'tok', refreshToken: async () => 'tok2' };
const MID = 'a'.repeat(32);
const IID = 'c'.repeat(32);

function setup(reply: (path: string) => FakeReply = () => ({ json: {} })) {
  const ff = fakeFetch((r) => reply(r.path));
  const timeouts: (number | undefined)[] = [];
  const fetch: FetchLike = (input, init) => {
    timeouts.push(init.timeoutMs);
    return ff.fetch(input, init);
  };
  const client = new ApiClient({ baseUrl: 'https://llm.brb-tech.uz', fetch, tokens: tp });
  return { ...ff, timeouts, meetings: createMeetingsApi(client), actions: createActionsApi(client) };
}

describe('CRM API wrappers', () => {
  it('32 action item -> CRM: POST with the optional body and the long AI timeout', async () => {
    const s = setup(() => ({ json: { status: 'failed', proposal: null, text: null, reason: 'crm_not_connected', item: null } }));
    const r = await s.meetings.actionItemToCrm(MID, IID);
    expect(r.reason).toBe('crm_not_connected');
    await s.meetings.actionItemToCrm(MID, IID, { force: true });
    expect(s.calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ['POST', `/api/v1/meetings/${MID}/action-items/${IID}/crm`, {}],
      ['POST', `/api/v1/meetings/${MID}/action-items/${IID}/crm`, { force: true }],
    ]);
    expect(s.timeouts).toEqual([AI_TIMEOUT_MS, AI_TIMEOUT_MS]);
    expect(AI_TIMEOUT_MS).toBeGreaterThan(120_000); // server MEETINGS_CRM_TIMEOUT=120 s dan keyin uzadi
  });

  it('confirm / cancel / get go to /api/v1/actions/{token} (token encoded), Bearer + client header', async () => {
    const s = setup(() => ({ json: { token: 'a/b', status: 'executed', ok: true, result: { key: 'DVSIB-231' } } }));
    await expect(s.actions.confirm('a/b')).resolves.toMatchObject({ status: 'executed', result: { key: 'DVSIB-231' } });
    await s.actions.cancel('tok-1');
    await s.actions.get('tok-1');
    expect(s.calls.map((c) => [c.method, c.path])).toEqual([
      ['POST', '/api/v1/actions/a%2Fb/confirm'],
      ['POST', '/api/v1/actions/tok-1/cancel'],
      ['GET', '/api/v1/actions/tok-1'],
    ]);
    expect(s.calls[0].headers.Authorization).toBe('Bearer tok');
    expect(s.calls[0].headers['X-Venera-Client']).toBe('mobile');
    expect(s.timeouts.slice(0, 2)).toEqual([ACTION_TIMEOUT_MS, ACTION_TIMEOUT_MS]);
  });

  it('ask also waits for v3 (long timeout)', async () => {
    const s = setup(() => ({ json: {} }));
    await s.meetings.ask(MID, { question: 'q' });
    expect(s.timeouts).toEqual([AI_TIMEOUT_MS]);
  });

  it('404 and 410 mean "expired", other errors do not', async () => {
    const s = setup((p) => (p.endsWith('/x410/confirm') ? envelope(410, 'Taklif muddati tugagan', { code: 'expired' }) : p.endsWith('/x404/confirm') ? envelope(404, 'Topilmadi') : envelope(502, 'xato')));
    const err = async (token: string) => s.actions.confirm(token).catch((e: unknown) => e);
    expect(isExpiredError(await err('x410'))).toBe(true);
    expect(isExpiredError(await err('x404'))).toBe(true);
    expect(isExpiredError(await err('x502'))).toBe(false);
    expect(isExpiredError(new Error('x'))).toBe(false);
  });
});

describe('CRM controller (crmStore)', () => {
  function make(
    over: {
      crm?: () => Promise<CrmResult>;
      confirm?: (t: string) => Promise<unknown>;
      cancel?: (t: string) => Promise<unknown>;
      get?: (t: string) => Promise<unknown>;
      serverItems?: () => Promise<{ items: ActionItem[] }>;
    } = {},
  ) {
    // gcTime: Infinity - keshda taymer qolmasin (Jest jarayoni toza tugasin).
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    qc.setQueryData(qk.actionItems(MID), { items: [actionItem] });
    qc.setQueryData(qk.myItems('open'), { items: [globalItem] });
    const meetings = {
      actionItemToCrm: jest.fn(over.crm ?? (async () => ({ status: 'failed', proposal: null, text: null, reason: 'empty', item: null }) as CrmResult)),
      // Serverdagi vazifa (tasdiq javobi yo'qolganda tekshiriladi): sukut bo'yicha - kutilayotgan taklif.
      actionItems: jest.fn(over.serverItems ?? (async () => ({ items: [{ ...actionItem, crm: crmState() }] }))),
    };
    const actions = {
      confirm: jest.fn(over.confirm ?? (async (token: string) => ({ token, status: 'executed', ok: true, result: { key: 'DVSIB-231' } }))),
      cancel: jest.fn(over.cancel ?? (async (token: string) => ({ token, status: 'cancelled' }))),
      get: jest.fn(over.get ?? (async (token: string) => ({ token, status: 'pending' }))),
    };
    const ctrl = createCrmController({ meetings, actions, qc } as never);
    const item = () => qc.getQueryData<{ items: ActionItem[] }>(qk.actionItems(MID))!.items[0];
    const mine = () => qc.getQueryData<{ items: GlobalActionItem[] }>(qk.myItems('open'))!.items[0];
    return { qc, meetings, actions, ctrl, item, mine };
  }
  const ref = { id: IID, meetingId: MID };

  beforeEach(() => useCrmStore.getState().reset());

  it('proposed: the stored proposal lands on the item in every cached list; local state cleared', async () => {
    const p = crmProposal();
    const { ctrl, item, mine, meetings } = make({ crm: async () => ({ status: 'proposed', proposal: p, text: null, reason: null, item: { ...actionItem, crm: crmState({}, p) } }) });
    await ctrl.request(ref);
    expect(meetings.actionItemToCrm).toHaveBeenCalledWith(MID, IID, {});
    expect(item().crm).toMatchObject({ token: 'tok-1', status: 'pending', proposal: p });
    expect(mine().crm).toMatchObject({ token: 'tok-1', status: 'pending' });
    expect(mine().meetingTitle).toBe('Narxlar'); // boshqa maydonlar saqlanadi
    expect(useCrmStore.getState().local[IID]).toBeUndefined();
  });

  it('proposed without an item (contract variant): built from the proposal', async () => {
    const p = crmProposal({ token: 'tok-9' });
    const { ctrl, item } = make({ crm: async () => ({ status: 'proposed', proposal: p, text: null, reason: null, item: null }) });
    await ctrl.request(ref, { force: true });
    expect(item().crm).toEqual({ token: 'tok-9', status: 'pending', proposal: p, expiresAt: p.expires_at, result: null, updatedAt: null });
  });

  it('double tap while waiting sends ONE request; the busy state is visible meanwhile', async () => {
    let resolve!: (r: CrmResult) => void;
    const { ctrl, meetings } = make({ crm: () => new Promise<CrmResult>((r) => (resolve = r)) });
    const first = ctrl.request(ref);
    const second = ctrl.request(ref);
    expect(useCrmStore.getState().local[IID]).toMatchObject({ kind: 'requesting' });
    ctrl.dismiss(ref); // so'rov paytida yopib bo'lmaydi
    expect(useCrmStore.getState().local[IID]).toMatchObject({ kind: 'requesting' });
    resolve({ status: 'answered', proposal: null, text: 'Qaysi loyiha?', reason: null, item: null });
    await Promise.all([first, second]);
    expect(meetings.actionItemToCrm).toHaveBeenCalledTimes(1);
    expect(useCrmStore.getState().local[IID]).toEqual({ kind: 'answered', text: 'Qaysi loyiha?' });
    ctrl.dismiss(ref);
    expect(useCrmStore.getState().local[IID]).toBeUndefined();
  });

  it('failed reasons and transport errors become a local failure', async () => {
    const a = make({ crm: async () => ({ status: 'failed', proposal: null, text: null, reason: 'crm_not_connected', item: null }) });
    await a.ctrl.request(ref);
    expect(useCrmStore.getState().local[IID]).toEqual({ kind: 'failed', reason: 'crm_not_connected' });
    const b = make({ crm: async () => Promise.reject(new ApiError(0, 'timeout', 'x')) });
    await b.ctrl.request(ref);
    // Transport xatosi: so'rovdan oldingi kalit eslab qolinadi (server keyin saqlagan taklif xatoni yopadi).
    expect(useCrmStore.getState().local[IID]).toEqual({ kind: 'failed', reason: 'timeout', prevToken: null });
    const c = make({ crm: async () => ({ status: 'answered', proposal: null, text: '  ', reason: null, item: null }) });
    await c.ctrl.request(ref);
    expect(useCrmStore.getState().local[IID]).toEqual({ kind: 'failed', reason: 'assistant_error' });
  });

  it('confirm: executed -> session outcome + item marked executed with the CRM key; a second confirm is ignored', async () => {
    const { qc, ctrl, item, actions } = make();
    qc.setQueryData(qk.actionItems(MID), { items: [{ ...actionItem, crm: crmState() }] });
    await ctrl.confirm(ref, 'tok-1');
    await ctrl.confirm(ref, 'tok-1');
    expect(actions.confirm).toHaveBeenCalledTimes(1);
    expect(useCrmStore.getState().settled['tok-1']).toEqual({ status: 'executed', result: { key: 'DVSIB-231' }, error: null });
    expect(item().crm).toMatchObject({ status: 'executed', result: { key: 'DVSIB-231' } });
    expect(useCrmStore.getState().busy['tok-1']).toBeUndefined();
  });

  it('confirm: ok=false is a failure (platform did not accept)', async () => {
    const { ctrl } = make({ confirm: async (token) => ({ token, status: 'executed', ok: false, error: 'Loyiha yopiq' }) });
    await ctrl.confirm(ref, 'tok-1');
    expect(useCrmStore.getState().settled['tok-1']).toEqual({ status: 'failed', result: null, error: 'Loyiha yopiq' });
  });

  it('confirm: 410 / 404 -> expired (not an error)', async () => {
    const { qc, ctrl, item } = make({ confirm: async () => Promise.reject(new ApiError(410, 'expired', 'Taklif muddati tugagan')) });
    qc.setQueryData(qk.actionItems(MID), { items: [{ ...actionItem, crm: crmState() }] });
    await ctrl.confirm(ref, 'tok-1');
    expect(useCrmStore.getState().settled['tok-1']).toMatchObject({ status: 'expired' });
    expect(useCrmStore.getState().actionError['tok-1']).toBeUndefined();
    expect(item().crm?.status).toBe('expired');
  });

  it('confirm: a network error keeps the proposal confirmable and shows the error', async () => {
    let fail = true;
    const { ctrl, actions } = make({
      confirm: async (token) => {
        if (fail) throw new ApiError(0, 'network', 'offline');
        return { token, status: 'executed', ok: true };
      },
    });
    await ctrl.confirm(ref, 'tok-1');
    expect(useCrmStore.getState().settled['tok-1']).toBeUndefined();
    expect(useCrmStore.getState().actionError['tok-1']).toBe('network');
    fail = false;
    await ctrl.confirm(ref, 'tok-1');
    expect(actions.confirm).toHaveBeenCalledTimes(2);
    expect(useCrmStore.getState().actionError['tok-1']).toBeUndefined();
    expect(useCrmStore.getState().settled['tok-1']).toMatchObject({ status: 'executed' });
  });

  it('cancel -> cancelled; a reply with status "pending" or none at all still settles by verb', async () => {
    const { ctrl } = make({ cancel: async (token) => ({ token, status: 'pending' }) });
    await ctrl.cancel(ref, 'tok-1');
    expect(useCrmStore.getState().settled['tok-1']).toMatchObject({ status: 'cancelled' });
    const d = make({ cancel: async (token) => ({ token }) });
    await d.ctrl.cancel(ref, 'tok-2');
    expect(useCrmStore.getState().settled['tok-2']).toMatchObject({ status: 'cancelled' });
  });

  it('confirm: a reply without a status settles by ok (server proposal_outcome), never "failed" by default', async () => {
    const { ctrl, actions } = make({ confirm: async (token) => ({ token, ok: true, result: { key: 'DVSIB-231' } }) });
    await ctrl.confirm(ref, 'tok-1');
    expect(useCrmStore.getState().settled['tok-1']).toMatchObject({ status: 'executed', result: { key: 'DVSIB-231' } });
    expect(actions.get).not.toHaveBeenCalled();
  });

  it('request remembers which proposal the item had, so a newer stored one can replace a lost reply', async () => {
    const { qc, ctrl } = make({ crm: async () => Promise.reject(new ApiError(504, 'gateway_timeout', 'x')) });
    qc.setQueryData(qk.actionItems(MID), { items: [{ ...actionItem, crm: crmState({ status: 'expired' }) }] });
    await ctrl.request(ref, { force: true });
    expect(useCrmStore.getState().local[IID]).toEqual({ kind: 'failed', reason: 'gateway_timeout', prevToken: 'tok-1' });
  });

  it('lost confirm: the next tap checks first; executed on the server -> settled, no second confirm', async () => {
    let executed = false;
    const { ctrl, actions } = make({
      confirm: async () => {
        throw new ApiError(504, 'gateway_timeout', 'x');
      },
      serverItems: async () => ({ items: [{ ...actionItem, crm: crmState(executed ? { status: 'executed', result: { key: 'DVSIB-231' } } : {}) }] }),
    });
    await ctrl.confirm(ref, 'tok-1');
    expect(useCrmStore.getState().unsure['tok-1']).toBe(true);
    expect(useCrmStore.getState().actionError['tok-1']).toBe('gateway_timeout');
    executed = true; // server tasdiqni keyinroq tugatdi
    await ctrl.confirm(ref, 'tok-1');
    expect(actions.confirm).toHaveBeenCalledTimes(1);
    expect(useCrmStore.getState().settled['tok-1']).toEqual({ status: 'executed', result: { key: 'DVSIB-231' }, error: null });
    expect(useCrmStore.getState().unsure['tok-1']).toBeUndefined();
  });

  it('lost confirm then 404 -> "unknown" (the item status is not overwritten with expired)', async () => {
    let n = 0;
    const { qc, ctrl, item } = make({
      confirm: async () => {
        throw ++n === 1 ? new ApiError(0, 'timeout', 'x') : new ApiError(404, 'not_found', 'x');
      },
      get: async () => Promise.reject(new ApiError(404, 'not_found', 'x')),
    });
    qc.setQueryData(qk.actionItems(MID), { items: [{ ...actionItem, crm: crmState() }] });
    await ctrl.confirm(ref, 'tok-1');
    await ctrl.confirm(ref, 'tok-1');
    expect(useCrmStore.getState().settled['tok-1']).toMatchObject({ status: 'unknown' });
    expect(item().crm?.status).toBe('pending');
  });

  it('lost confirm, the service still says pending: the confirm is sent again (safe)', async () => {
    let n = 0;
    const { ctrl, actions } = make({
      confirm: async (token) => {
        if (++n === 1) throw new ApiError(0, 'network', 'x');
        return { token, status: 'executed', ok: true };
      },
    });
    await ctrl.confirm(ref, 'tok-1');
    await ctrl.confirm(ref, 'tok-1');
    expect(actions.get).toHaveBeenCalled();
    expect(actions.confirm).toHaveBeenCalledTimes(2);
    expect(useCrmStore.getState().settled['tok-1']).toMatchObject({ status: 'executed' });
  });

  it('reset clears everything (sign-out)', async () => {
    const { ctrl } = make({ crm: async () => ({ status: 'answered', proposal: null, text: 'x', reason: null, item: null }) });
    await ctrl.request(ref);
    useCrmStore.getState().reset();
    expect(useCrmStore.getState()).toMatchObject({ local: {}, busy: {}, actionError: {}, settled: {}, unsure: {} });
  });
});
