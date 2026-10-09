/**
 * Taklif kartasining ko'rsatish mantig'i (sof funksiyalar - test oson).
 *
 * Qoidalar chatdagi kartalar bilan BIR XIL: obyekt nomi web `targetLabel`
 * (`apps/web/src/api/actions.api.ts`), qiymat matni bot `action_text`
 * (`apps/api/app/bot/render.py`) - XOM JSON hech qachon ko'rsatilmaydi, natija
 * holati web `ActionCard.vue` va server `proposal_outcome` dagidek.
 */
import type { ActionCrm, ActionItem, ActionProposal, ActionResult, ActionStatus } from '@/api/types';
import type { TFn, TKey } from '@/i18n';

/**
 * Obyektning odam o'qiydigan nomi ("DVSIB-123", loyiha nomi). Bo'lmasa bo'sh - masalan
 * YANGI vazifa (`{kind: "new_issue", key: null}`): uning nomi va loyihasi o'zgarishlar
 * qatorida bor, xom JSON qatori esa shovqin edi (web bilan aynan bir xil qoida).
 */
export function targetLabel(target: unknown): string {
  if (target == null || target === '') return '';
  if (typeof target !== 'object') return String(target);
  const o = target as Record<string, unknown>;
  const name = o.title ?? o.name ?? o.key ?? o.id;
  return name != null && name !== '' ? String(name) : '';
}

/** Qiymatning ko'rinadigan matni: obyekt - nomi/kaliti yoki oddiy qiymatlari, ro'yxat - vergul bilan. */
export function valueText(value: unknown): string {
  if (value == null || value === '') return '—';
  if (Array.isArray(value)) return value.map(valueText).filter((v) => v !== '—').join(', ') || '—';
  if (typeof value === 'object') {
    const o = value as Record<string, unknown>;
    for (const k of ['title', 'name', 'key', 'summary', 'id']) {
      const v = o[k];
      if (v != null && v !== '' && typeof v !== 'object') return String(v);
    }
    const scalars = Object.values(o).filter((v) => (typeof v === 'string' || typeof v === 'number') && v !== '');
    return scalars.map(String).join(' · ') || '—';
  }
  if (typeof value === 'boolean') return value ? '✓' : '✕';
  return String(value);
}

/**
 * CRM muhimlik qiymatlari inglizcha keladi ("High", "Medium") - o'zbekcha yorliqlar yonida
 * aralash til bo'lmasin. Faqat ko'rsatish: CRM ga taklifdagi asl qiymat yoziladi.
 */
const PRIORITY_VALUES: Record<string, TKey> = {
  highest: 'sum.severity.high',
  high: 'sum.severity.high',
  critical: 'sum.severity.high',
  urgent: 'sum.severity.high',
  medium: 'sum.severity.medium',
  normal: 'sum.priority.normal',
  low: 'sum.severity.low',
  lowest: 'sum.severity.low',
  minor: 'sum.severity.low',
};

function isPriorityField(field: string | undefined | null): boolean {
  return (field ?? '').trim().toLowerCase() === 'priority';
}

/** Maydon qiymati: muhimlik so'zlari tarjima qilinadi, qolgani `valueText`. */
export function fieldValueText(field: string | undefined | null, value: unknown, t: TFn): string {
  const text = valueText(value);
  if (!isPriorityField(field)) return text;
  const key = PRIORITY_VALUES[text.trim().toLowerCase()];
  return key ? t(key) : text;
}

/** Xizmat ko'p ishlatadigan maydon nomlari -> interfeys tilidagi yorliq. */
const FIELD_KEYS: Record<string, TKey> = {
  title: 'crm.field.title',
  summary: 'crm.field.title',
  name: 'crm.field.title',
  description: 'crm.field.description',
  assignee: 'crm.field.assignee',
  assignee_id: 'crm.field.assignee',
  executor: 'crm.field.assignee',
  responsible: 'crm.field.assignee',
  project: 'crm.field.project',
  project_id: 'crm.field.project',
  project_key: 'crm.field.project',
  due: 'crm.field.due',
  due_date: 'crm.field.due',
  duedate: 'crm.field.due',
  deadline: 'crm.field.due',
  priority: 'crm.field.priority',
  status: 'crm.field.status',
  reporter: 'crm.field.reporter',
  author: 'crm.field.reporter',
  start_date: 'crm.field.start',
  labels: 'crm.field.labels',
  tags: 'crm.field.labels',
  type: 'crm.field.type',
  issue_type: 'crm.field.type',
};

/**
 * Maydon yorlig'i: tanish texnik nom (`due_date`) tarjima qilinadi, boshqasi
 * odamcha yoziladi (`story_points` -> "Story points"); xizmat o'zi o'zbekcha
 * yozgan nom ("Loyiha") o'zgarmaydi.
 */
export function fieldLabel(field: string | undefined | null, t: TFn): string {
  const raw = (field ?? '').trim();
  if (!raw) return t('crm.change');
  const key = FIELD_KEYS[raw.toLowerCase().replace(/[\s-]+/g, '_')];
  if (key) return t(key);
  if (/^[a-z0-9]+(?:_[a-z0-9]+)+$/i.test(raw) || /^[a-z]+$/.test(raw)) {
    const words = raw.replace(/_/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  return raw;
}

export interface ChangeRow {
  label: string;
  /** Eski qiymat (bo'lsa) - ustidan chizilib ko'rsatiladi. */
  from: string | null;
  to: string;
}

/** Obyekt va o'zgarishlar - "yorliq: qiymat" qatorlari. */
export function proposalRows(p: ActionProposal, t: TFn): ChangeRow[] {
  const rows: ChangeRow[] = [];
  const target = targetLabel(p.target);
  if (target) rows.push({ label: t('crm.target'), from: null, to: target });
  for (const c of p.changes ?? []) {
    if (!c || typeof c !== 'object' || (!c.field && c.to === undefined)) continue;
    const hasFrom = c.from !== undefined && c.from !== null && c.from !== '';
    rows.push({ label: fieldLabel(c.field, t), from: hasFrom ? fieldValueText(c.field, c.from, t) : null, to: fieldValueText(c.field, c.to, t) });
  }
  return rows;
}

/** YANGI vazifa yaratish taklifimi (`crm_create_issue`, `create_task`...) - kartaning sarlavhasi uchun. */
export function isCreateOperation(operation: string | null | undefined): boolean {
  return /create|new/i.test(operation ?? '');
}

/** Ogohlantirishlar: faqat bo'sh bo'lmagan satrlar. */
export function proposalWarnings(p: ActionProposal): string[] {
  return (p.warnings ?? []).filter((w): w is string => typeof w === 'string' && w.trim() !== '');
}

/** CRM qaytargan ko'rsatkich (yaratilgan vazifa kaliti) - web `resultText` bilan bir xil. */
export function resultKey(result: Record<string, unknown> | null | undefined): string {
  if (!result) return '';
  const key = result.key ?? result.id ?? result.number;
  return key != null && key !== '' && typeof key !== 'object' ? String(key) : '';
}

/** CRM qaytargan havola (bo'lsa) - faqat https (boshqa sxema telefonda ochilmaydi). */
export function resultLink(result: Record<string, unknown> | null | undefined): string | null {
  if (!result) return null;
  for (const k of ['url', 'link', 'web_url', 'browse_url', 'html_url']) {
    const v = result[k];
    if (typeof v === 'string' && /^https:\/\/[^\s]+$/i.test(v.trim())) return v.trim();
  }
  return null;
}

export function expiresAtMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

/** Qolgan vaqt yorlig'i: daqiqadan ko'p - butun daqiqa (yuqoriga), oxirgi daqiqa - soniyalar. */
export function timeLeftText(leftMs: number, t: TFn): string {
  if (leftMs <= 0) return '';
  if (leftMs < 60_000) return t('crm.secondsLeft', { n: Math.max(1, Math.ceil(leftMs / 1000)) });
  return t('crm.minutesLeft', { n: Math.ceil(leftMs / 60_000) });
}

/**
 * `unknown` - tasdiq javobi yo'qolgan (tarmoq / timeout), keyin xizmat taklifni tanimadi
 * (404/410): vazifa CRMga qo'shilgan bo'lishi HAM, qo'shilmagan bo'lishi HAM mumkin. Buni
 * "muddati tugagan" deb ko'rsatish xavfli - odam qayta yuborib, CRMda ikki vazifa yaratadi.
 */
export type Outcome = 'pending' | 'executed' | 'cancelled' | 'expired' | 'failed' | 'unknown';

/**
 * Vazifada SAQLANGAN holat -> karta holati. `ok === false` - platforma "bajarildi" desa ham
 * natija yo'q: bu muvaffaqiyatsizlik (web `ActionCard`).
 */
export function outcomeOf(status: ActionStatus | null | undefined, ok?: boolean | null): Outcome {
  if (status === 'executed') return ok === false ? 'failed' : 'executed';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'expired') return 'expired';
  if (status === 'pending') return 'pending';
  return 'failed';
}

/**
 * Tasdiqlash / rad etish JAVOBI -> natija, server `actions.proposal_outcome` qoidasi bilan:
 * xizmat yakuniy holatni o'zi aytsa - o'sha; aytmasa (yo'q, `pending` yoki noma'lum so'z) -
 * fe'l bo'yicha: rad etish - `cancelled`, tasdiq - `ok` bo'yicha. `ok` ham yo'q bo'lsa -
 * `null`: natija noma'lum, holatni tekshirish kerak (taxmin qilinmaydi).
 *
 * Yagona farq (web `ActionCard` kabi): `executed` + `ok === false` - `failed`.
 */
export function decisionOutcome(verb: 'confirm' | 'cancel', res: Pick<ActionResult, 'status' | 'ok'>): Outcome | null {
  const status = res.status;
  if (status === 'executed') return res.ok === false ? 'failed' : 'executed';
  if (status === 'failed') return 'failed';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'expired') return 'expired';
  if (verb === 'cancel') return 'cancelled';
  if (res.ok === true) return 'executed';
  if (res.ok === false) return 'failed';
  return null;
}

/** Server `item` bermagan bo'lsa - taklifning o'zidan vazifaning CRM holati. */
export function crmFromProposal(p: ActionProposal): ActionCrm {
  return { token: p.token, status: 'pending', proposal: p, expiresAt: p.expires_at ?? null, result: null, updatedAt: null };
}

/** Shu sessiyada (telefonda) olingan natija - server holati yangilanguncha ustun. */
export interface SessionOutcome {
  status: Outcome;
  result: Record<string, unknown> | null;
  error: string | null;
}

export type LocalFlow =
  | { kind: 'requesting'; startedAt: number }
  | { kind: 'answered'; text: string }
  /**
   * `prevToken` - so'rov boshlanganda vazifada bo'lgan taklif kaliti. Javob yo'qolsa ham
   * (nginx 504, tarmoq) server ishni tugatib taklifni SAQLAYDI: vazifada YANGI kalit paydo
   * bo'lsa, bu xato eskirgan - taklif kartasi ko'rsatiladi.
   */
  | { kind: 'failed'; reason: string; prevToken?: string | null };

/** Vazifa ostida nima chiziladi. */
export type CrmView =
  | { kind: 'hidden' }
  | { kind: 'idle'; note: 'cancelled' | null }
  | { kind: 'requesting'; startedAt: number }
  | { kind: 'answered'; text: string }
  | { kind: 'failed'; reason: string }
  | { kind: 'proposal'; crm: ActionCrm; proposal: ActionProposal; outcome: Outcome; session: SessionOutcome | null }
  | { kind: 'added'; key: string; link: string | null };

/**
 * Holatni yig'ish: telefondagi jarayon (so'rov ketmoqda, javob, xato) birinchi; keyin
 * vazifada saqlangan taklif (server) - shu sessiyadagi tasdiq natijasi bilan.
 *
 *  - kutilayotgan (pending) taklif - to'liq karta, muddati tugaguncha tasdiqlanadi;
 *  - shu yerda tasdiqlangan - karta muvaffaqiyat bilan; avvalroq tasdiqlangan - ixcham
 *    "CRMga qo'shilgan" qatori;
 *  - bekor qilingan - yana "CRMga qo'shish" tugmasi (izoh bilan);
 *  - muddati o'tgan / bajarilmagan / natija noma'lum - karta yakuniy holatda, "Yangi taklif olish" bilan.
 *
 * Telefondagi xato, agar serverda shundan keyin yangi taklif saqlangan bo'lsa, eskirgan
 * (`prevToken`). Serverdagi `executed` esa telefondagi "muddati tugagan" / "noma'lum" dan
 * ustun: vazifa CRMda bor, odamga "qayta yuborish" taklif qilinmaydi.
 */
export function deriveCrmView(
  item: Pick<ActionItem, 'status'> & { crm?: ActionCrm | null },
  local: LocalFlow | undefined,
  session: SessionOutcome | undefined,
): CrmView {
  const crm = item.crm ?? null;
  const superseded = local?.kind === 'failed' && local.prevToken !== undefined && !!crm && crm.token !== local.prevToken;
  if (local && !superseded) return local;
  if (!crm) return item.status === 'dismissed' ? { kind: 'hidden' } : { kind: 'idle', note: null };
  const server = outcomeOf(crm.status);
  const own = session && !(server === 'executed' && (session.status === 'expired' || session.status === 'unknown')) ? session : null;
  const status = own?.status ?? server;
  if (status === 'cancelled') return item.status === 'dismissed' ? { kind: 'hidden' } : { kind: 'idle', note: 'cancelled' };
  if (status === 'executed' && (!own || !crm.proposal)) {
    const result = own?.result ?? crm.result;
    return { kind: 'added', key: resultKey(result), link: resultLink(result) };
  }
  if (!crm.proposal) return item.status === 'dismissed' ? { kind: 'hidden' } : { kind: 'idle', note: null };
  return { kind: 'proposal', crm, proposal: crm.proposal, outcome: status, session: own };
}
