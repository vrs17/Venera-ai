/**
 * Vazifani CRM ga yuborish jarayoni - ekrandan TASHQARIDA (zustand + oddiy funksiyalar).
 *
 * NIMA UCHUN global: v3 taklifni 5-30 s (eng ko'pi 120 s) tayyorlaydi. Odam shu payt
 * ekrandan chiqib ketishi, boshqa yig'ilishga yoki "Vazifalarim" ga o'tishi mumkin -
 * so'rov to'xtamaydi, natija shu yerga yoziladi va vazifa qayerda ko'rinsa, o'sha
 * yerda chiqadi. Komponent o'chgan bo'lsa ham setState yo'q (faqat shu ombor va
 * React Query keshi).
 *
 * Ikki marta bosish: `requesting` holatidagi vazifaga ikkinchi so'rov ketmaydi; taklif
 * kaliti band (`busy`) yoki yakunlangan (`settled`) bo'lsa - tasdiq ham ketmaydi.
 *
 * Javob yo'qolsa (tarmoq, 60 s timeout, nginx 502/504) - so'rov serverda baribir bajarilgan
 * bo'lishi mumkin. Shuning uchun:
 *  - taklif so'rovi: qayta urinish `force` SIZ (server saqlagan taklifni darhol qaytaradi,
 *    v3 ga qayta bormaydi), saqlangan yangi taklif esa xatoni o'zi yopadi (`prevToken`);
 *  - tasdiq: kalit `unsure` deb belgilanadi va QAYTA yuborishdan oldin haqiqiy holat
 *    tekshiriladi (vazifa + `GET /actions/{token}`). Shundan keyingi 404/410 - "muddati
 *    tugagan" emas, "natija noma'lum" (CRMda bo'lishi mumkin) - aks holda ikki vazifa.
 *
 * Doimiy holat SERVERDA (vazifaning `crm` maydoni): kutilayotgan taklif, tasdiqlangan,
 * bekor qilingan. Bu ombor faqat jarayon va shu sessiyadagi natijani saqlaydi -
 * chiqishda tozalanadi (`reset`).
 */
import type { QueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import { create } from 'zustand';

import { isExpiredError, type ActionsApi } from '@/api/actions';
import { ApiError } from '@/api/client';
import type { MeetingsApi } from '@/api/meetings';
import type { ActionCrm, ActionItem } from '@/api/types';
import { qk } from '@/features/meeting/queries';

import { crmFromProposal, decisionOutcome, outcomeOf, type LocalFlow, type SessionOutcome } from './proposalModel';

export interface CrmState {
  /** Vazifa id -> jarayon (so'rov ketmoqda / matnli javob / xato). */
  local: Record<string, LocalFlow>;
  /** Taklif kaliti -> tasdiqlanmoqda / rad etilmoqda / natija tekshirilmoqda. */
  busy: Record<string, Busy>;
  /** Taklif kaliti -> tasdiqlashdagi tarmoq/xizmat xatosi (karta tasdiqlanadigan bo'lib qoladi). */
  actionError: Record<string, string>;
  /** Taklif kaliti -> shu sessiyadagi natija. */
  settled: Record<string, SessionOutcome>;
  /** Taklif kaliti -> tasdiq javobi yo'qolgan: keyingi bosishda avval holat tekshiriladi. */
  unsure: Record<string, true>;
  reset(): void;
}

export type Busy = 'confirm' | 'cancel' | 'check';

const EMPTY = { local: {}, busy: {}, actionError: {}, settled: {}, unsure: {} };

export const useCrmStore = create<CrmState>()((set) => ({
  ...EMPTY,
  reset: () => set({ ...EMPTY }),
}));

function put<K extends 'local' | 'busy' | 'actionError' | 'settled' | 'unsure'>(field: K, key: string, value: CrmState[K][string] | undefined) {
  useCrmStore.setState((s) => {
    const next = { ...s[field] } as Record<string, unknown>;
    if (value === undefined) delete next[key];
    else next[key] = value;
    return { [field]: next } as Partial<CrmState>;
  });
}

type ItemRef = Pick<ActionItem, 'id' | 'meetingId'>;

/** Vazifaning `crm` maydonini keshdagi HAMMA ro'yxatlarda yangilash (yig'ilish tabi + "Vazifalarim"). */
export function patchItemCrm(qc: QueryClient, ref: ItemRef, fn: (crm: ActionCrm | null) => ActionCrm | null): void {
  const apply = (old: { items: ActionItem[] } | undefined) =>
    old ? { ...old, items: old.items.map((i) => (i.id === ref.id ? { ...i, crm: fn(i.crm ?? null) } : i)) } : old;
  qc.setQueryData<{ items: ActionItem[] }>(qk.actionItems(ref.meetingId), apply);
  for (const [key] of qc.getQueriesData<{ items: ActionItem[] }>({ queryKey: ['action-items'] })) {
    qc.setQueryData<{ items: ActionItem[] }>(key, apply);
  }
}

/** Vazifaning keshdagi CRM holati (yig'ilish tabi yoki "Vazifalarim") - so'rovdan oldingi kalit uchun. */
function cachedCrm(qc: QueryClient, ref: ItemRef): ActionCrm | null {
  const own = qc.getQueryData<{ items: ActionItem[] }>(qk.actionItems(ref.meetingId))?.items.find((i) => i.id === ref.id);
  if (own) return own.crm ?? null;
  for (const [, data] of qc.getQueriesData<{ items: ActionItem[] }>({ queryKey: ['action-items'] })) {
    const hit = data?.items.find((i) => i.id === ref.id);
    if (hit) return hit.crm ?? null;
  }
  return null;
}

function refresh(qc: QueryClient, ref: ItemRef): void {
  void qc.invalidateQueries({ queryKey: qk.actionItems(ref.meetingId) });
  void qc.invalidateQueries({ queryKey: ['action-items'] });
}

function vibrate(type: Haptics.NotificationFeedbackType): void {
  try {
    void Haptics.notificationAsync(type).catch(() => {});
  } catch {
    /* tebranish yo'q - muhim emas */
  }
}

/** Server sabab kodi yoki ApiError kodi (`network`, `timeout`, `rate_limited`...). */
export function failureCode(err: unknown): string {
  return err instanceof ApiError ? err.code : 'network';
}

/** Javob yo'qolgan bo'lishi mumkin (so'rov serverda bajarilgan bo'lishi mumkin) - natija noma'lum. */
const LOST = new Set(['network', 'timeout', 'gateway_timeout', 'bad_gateway']);

export function isLostReply(err: unknown): boolean {
  return LOST.has(failureCode(err));
}

export interface CrmDeps {
  meetings: Pick<MeetingsApi, 'actionItemToCrm' | 'actionItems'>;
  actions: Pick<ActionsApi, 'confirm' | 'cancel' | 'get'>;
  qc: QueryClient;
}

export function createCrmController({ meetings, actions, qc }: CrmDeps) {
  /**
   * Vazifa -> v3 -> taklif. `force` - eski (muddati o'tgan / rad etilgan / javob bo'lgan)
   * o'rniga yangisi. Xatodan keyin qayta urinish `force` SIZ: javob yo'qolgan bo'lsa, server
   * saqlagan taklif darhol qaytadi (v3 ga qayta 120 s kutish va soatlik limit sarflanmaydi).
   */
  async function request(ref: ItemRef, opts: { force?: boolean } = {}): Promise<void> {
    if (useCrmStore.getState().local[ref.id]?.kind === 'requesting') return;
    const prevToken = cachedCrm(qc, ref)?.token ?? null;
    put('local', ref.id, { kind: 'requesting', startedAt: Date.now() });
    try {
      const r = await meetings.actionItemToCrm(ref.meetingId, ref.id, opts.force ? { force: true } : {});
      if (r.status === 'proposed' && r.proposal?.token) {
        const crm = r.item?.crm?.token === r.proposal.token ? r.item.crm : crmFromProposal(r.proposal);
        patchItemCrm(qc, ref, () => crm);
        put('local', ref.id, undefined);
      } else if (r.status === 'answered' && r.text?.trim()) {
        put('local', ref.id, { kind: 'answered', text: r.text });
      } else {
        put('local', ref.id, { kind: 'failed', reason: r.reason || 'assistant_error' });
      }
    } catch (e) {
      // Yangilangan ro'yxatda yangi taklif bo'lsa, `deriveCrmView` shu xatoni o'zi yopadi.
      put('local', ref.id, { kind: 'failed', reason: failureCode(e), prevToken });
    } finally {
      refresh(qc, ref);
    }
  }

  /** Matnli javob / xatoni yopish - vazifa yana "CRMga qo'shish" holatiga. */
  function dismiss(ref: ItemRef): void {
    if (useCrmStore.getState().local[ref.id]?.kind === 'requesting') return;
    put('local', ref.id, undefined);
  }

  /**
   * Taklifning HAQIQIY holati (tasdiq javobi yo'qolganda). Avval vazifa: server tasdiqni
   * oxirigacha bajargan bo'lsa natijani shu yerga yozgan. Keyin xizmatning o'zi. Yakuniy
   * holat yoki `pending` (hali bajarilmagan - yuborish xavfsiz); bilib bo'lmasa - `null`.
   */
  async function lookup(ref: ItemRef, token: string): Promise<SessionOutcome | null> {
    try {
      const { items } = await meetings.actionItems(ref.meetingId);
      const crm = items.find((i) => i.id === ref.id)?.crm;
      if (crm?.token === token) {
        const status = outcomeOf(crm.status);
        if (status === 'executed' || status === 'failed' || status === 'cancelled') return { status, result: crm.result, error: null };
      }
    } catch {
      /* vazifani o'qib bo'lmadi - xizmatdan so'raladi */
    }
    try {
      const res = await actions.get(token);
      const s = res.status;
      if (s === 'pending') return { status: 'pending', result: null, error: null };
      if (s === 'executed' || s === 'failed' || s === 'cancelled' || s === 'expired') {
        const status = decisionOutcome('confirm', res) ?? 'failed';
        return { status, result: res.result ?? null, error: res.error ?? null };
      }
    } catch {
      /* 404/410 yoki tarmoq: kalit ishlatilganmi yoki muddati o'tganmi - bilib bo'lmaydi */
    }
    return null;
  }

  function settle(ref: ItemRef, token: string, verb: 'confirm' | 'cancel', outcome: SessionOutcome): void {
    put('settled', token, outcome);
    put('unsure', token, undefined);
    put('actionError', token, undefined);
    const { status } = outcome;
    if (status !== 'unknown') {
      patchItemCrm(qc, ref, (crm) => (crm && crm.token === token ? { ...crm, status, result: outcome.result ?? crm.result } : crm));
    }
    if (status === 'executed') vibrate(Haptics.NotificationFeedbackType.Success);
    else if (status === 'expired' || status === 'unknown') vibrate(Haptics.NotificationFeedbackType.Warning);
    else if (verb === 'confirm' && status === 'failed') vibrate(Haptics.NotificationFeedbackType.Error);
  }

  async function decide(ref: ItemRef, token: string, verb: 'confirm' | 'cancel'): Promise<void> {
    const st = useCrmStore.getState();
    if (st.busy[token] || st.settled[token]) return;
    const unsure = !!st.unsure[token];
    put('actionError', token, undefined);
    try {
      if (unsure) {
        // Oldingi tasdiq javobi yo'qolgan: qayta yuborishdan OLDIN - balki u bajarilgandir.
        // `pending` bo'lsa ham `unsure` qoladi: birinchi tasdiq serverda hali ishlayotgan
        // bo'lishi mumkin, keyingi 404 esa "muddati tugagan" emas, "noma'lum".
        put('busy', token, 'check');
        const known = await lookup(ref, token);
        if (known && known.status !== 'pending') return settle(ref, token, verb, known);
      }
      put('busy', token, verb);
      const res = await (verb === 'confirm' ? actions.confirm(token) : actions.cancel(token));
      const status = decisionOutcome(verb, res);
      if (status) return settle(ref, token, verb, { status, result: res.result ?? null, error: res.error ?? null });
      // Xizmat natijani aytmadi - holatni tekshiramiz, taxmin qilmaymiz.
      put('unsure', token, true);
      put('busy', token, 'check');
      const known = await lookup(ref, token);
      if (known && known.status !== 'pending') return settle(ref, token, verb, known);
      put('actionError', token, 'unverified');
    } catch (e) {
      if (isExpiredError(e)) {
        // Muddati o'tgan (404/410) - xato emas, taklifning holati. Lekin oldingi tasdiq javobi
        // yo'qolgan bo'lsa, kalit ishlatilgani uchun ham 404 bo'lishi mumkin - natija noma'lum.
        settle(ref, token, verb, { status: unsure ? 'unknown' : 'expired', result: null, error: null });
      } else if (isLostReply(e)) {
        put('unsure', token, true);
        put('busy', token, 'check');
        const known = await lookup(ref, token);
        if (known && known.status !== 'pending') settle(ref, token, verb, known);
        else {
          put('actionError', token, failureCode(e));
          vibrate(Haptics.NotificationFeedbackType.Error);
        }
      } else {
        put('actionError', token, failureCode(e));
        vibrate(Haptics.NotificationFeedbackType.Error);
      }
    } finally {
      put('busy', token, undefined);
      refresh(qc, ref);
    }
  }

  return {
    request,
    dismiss,
    confirm: (ref: ItemRef, token: string) => decide(ref, token, 'confirm'),
    cancel: (ref: ItemRef, token: string) => decide(ref, token, 'cancel'),
  };
}

export type CrmController = ReturnType<typeof createCrmController>;
