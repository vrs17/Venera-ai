/**
 * Taklif kartasining sof mantig'i: obyekt nomi (web `targetLabel` bilan bir xil),
 * qiymatlar HECH QACHON xom JSON emas, maydon yorliqlari, natija kaliti/havolasi,
 * qolgan vaqt va vazifaning CRM holati (saqlangan + shu sessiyadagi).
 */
import type { ActionCrm } from '@/api/types';
import {
  crmFromProposal,
  decisionOutcome,
  deriveCrmView,
  fieldLabel,
  fieldValueText,
  isCreateOperation,
  outcomeOf,
  proposalRows,
  proposalWarnings,
  resultKey,
  resultLink,
  targetLabel,
  timeLeftText,
  valueText,
} from '@/features/crm/proposalModel';
import { makeT } from '@/i18n';

import { crmProposal, crmState } from './fixtures/server';

const t = makeT('uz');

describe('targetLabel (web actions.api.ts parity)', () => {
  it.each([
    [null, ''],
    ['', ''],
    ['DVSIB-12', 'DVSIB-12'],
    [42, '42'],
    [{ title: 'Hisobot', key: 'X-1' }, 'Hisobot'],
    [{ name: 'Raqamli savdo' }, 'Raqamli savdo'],
    [{ key: 'DVSIB-231' }, 'DVSIB-231'],
    [{ id: 7 }, '7'],
    [{ kind: 'new_issue', key: null }, ''],
    [{ project: 'DVSIB' }, ''],
  ])('%j -> %j', (input, out) => {
    expect(targetLabel(input)).toBe(out);
  });
});

describe('valueText never shows raw JSON', () => {
  it.each([
    [null, '—'],
    ['', '—'],
    ['2026-10-10', '2026-10-10'],
    [3, '3'],
    [true, '✓'],
    [{ id: 42, name: 'Dilnoza Karimova' }, 'Dilnoza Karimova'],
    [{ key: 'DVSIB', name: 'Raqamli savdo' }, 'Raqamli savdo'],
    [{ summary: 'Vazifa' }, 'Vazifa'],
    [{ first: 'Aziz', last: 'Karimov', n: 2 }, 'Aziz · Karimov · 2'],
    [{ nested: { deep: 1 } }, '—'],
    [['a', { name: 'b' }, null], 'a, b'],
    [[], '—'],
  ])('%j -> %j', (input, out) => {
    const text = valueText(input);
    expect(text).toBe(out);
    expect(text).not.toMatch(/[{}[\]"]/);
  });
});

describe('fieldLabel', () => {
  it('translates well-known technical field names and humanises the rest', () => {
    expect(fieldLabel('due_date', t)).toBe('Muddat');
    expect(fieldLabel('assignee', t)).toBe("Mas'ul");
    expect(fieldLabel('Project', t)).toBe('Loyiha');
    expect(fieldLabel('story_points', t)).toBe('Story points');
    expect(fieldLabel("Mas'ul shaxs", t)).toBe("Mas'ul shaxs");
    expect(fieldLabel(undefined, t)).toBe("O'zgarish");
    expect(fieldLabel('due_date', makeT('ru'))).toBe('Срок');
    expect(fieldLabel('due_date', makeT('en'))).toBe('Due');
  });
});

describe('fieldValueText / isCreateOperation', () => {
  it('CRM priority words are shown in the UI language; other values and fields are untouched', () => {
    expect(fieldValueText('priority', 'High', t)).toBe('Yuqori');
    expect(fieldValueText('Priority', 'highest', t)).toBe('Yuqori');
    expect(fieldValueText('priority', 'Medium', t)).toBe("O'rta");
    expect(fieldValueText('priority', 'Normal', t)).toBe('Oddiy');
    expect(fieldValueText('priority', { name: 'Low' }, t)).toBe('Past');
    expect(fieldValueText('priority', 'P1', t)).toBe('P1');
    expect(fieldValueText('title', 'High', t)).toBe('High');
    expect(fieldValueText('priority', 'High', makeT('ru'))).toBe('Высокий');
  });

  it('create operations get the "new task" heading', () => {
    expect(isCreateOperation('crm_create_issue')).toBe(true);
    expect(isCreateOperation('new_task')).toBe(true);
    expect(isCreateOperation('crm_update_issue')).toBe(false);
    expect(isCreateOperation(null)).toBe(false);
  });
});

describe('proposalRows / warnings', () => {
  it('target first, then changes with readable from -> to; empty changes skipped', () => {
    const rows = proposalRows(
      crmProposal({
        target: { key: 'DVSIB-231', title: null },
        changes: [
          { field: 'priority', from: 'Normal', to: 'High' },
          { field: 'assignee', to: { id: 42, name: 'Dilnoza' } },
          {} as never,
          { field: 'due_date', from: '', to: '2026-10-10' },
        ],
      }),
      t,
    );
    expect(rows).toEqual([
      { label: 'Obyekt', from: null, to: 'DVSIB-231' },
      { label: 'Ustuvorlik', from: 'Oddiy', to: 'Yuqori' },
      { label: "Mas'ul", from: null, to: 'Dilnoza' },
      { label: 'Muddat', from: null, to: '2026-10-10' },
    ]);
  });

  it('a new issue has no target row (its title and project are changes)', () => {
    expect(proposalRows(crmProposal(), t)[0]).toEqual({ label: 'Nomi', from: null, to: 'Hisobotni yuborish' });
  });

  it('warnings: only non-empty strings', () => {
    expect(proposalWarnings(crmProposal({ warnings: ['a', '', '  ', 'b'] }))).toEqual(['a', 'b']);
    expect(proposalWarnings(crmProposal({ warnings: undefined }))).toEqual([]);
  });
});

describe('result key / link', () => {
  it('key -> id -> number; link only https', () => {
    expect(resultKey({ key: 'DVSIB-231', id: 5 })).toBe('DVSIB-231');
    expect(resultKey({ id: 5 })).toBe('5');
    expect(resultKey({ number: 12 })).toBe('12');
    expect(resultKey(null)).toBe('');
    expect(resultLink({ url: 'https://crm.brb-tech.uz/issues/DVSIB-231' })).toBe('https://crm.brb-tech.uz/issues/DVSIB-231');
    expect(resultLink({ url: 'javascript:alert(1)' })).toBeNull();
    expect(resultLink({ url: 'http://crm/x' })).toBeNull();
    expect(resultLink({ key: 'X' })).toBeNull();
  });
});

describe('time left', () => {
  it('minutes rounded up; seconds in the last minute; nothing when over', () => {
    expect(timeLeftText(14 * 60_000 + 1, t)).toBe('15 daq qoldi');
    expect(timeLeftText(60_000, t)).toBe('1 daq qoldi');
    expect(timeLeftText(42_300, t)).toBe('43 soniya qoldi');
    expect(timeLeftText(0, t)).toBe('');
    expect(timeLeftText(-5, t)).toBe('');
  });
});

describe('outcomeOf (server proposal_outcome parity)', () => {
  it.each([
    ['executed', true, 'executed'],
    ['executed', undefined, 'executed'],
    ['executed', false, 'failed'],
    ['cancelled', undefined, 'cancelled'],
    ['expired', undefined, 'expired'],
    ['pending', undefined, 'pending'],
    ['failed', false, 'failed'],
    ['weird', undefined, 'failed'],
  ] as const)('%s ok=%s -> %s', (status, ok, out) => {
    expect(outcomeOf(status, ok)).toBe(out);
  });
});

describe('decisionOutcome (server actions.proposal_outcome parity)', () => {
  it.each([
    ['confirm', 'executed', true, 'executed'],
    ['confirm', 'executed', undefined, 'executed'],
    ['confirm', 'executed', false, 'failed'], // web ActionCard: natija yo'q - muvaffaqiyatsiz
    ['confirm', 'failed', undefined, 'failed'],
    ['confirm', 'expired', undefined, 'expired'],
    ['confirm', 'cancelled', undefined, 'cancelled'],
    // Holat yo'q / pending / noma'lum so'z - fe'l va `ok` bo'yicha (ilgari "Bajarilmadi" bo'lardi).
    ['confirm', undefined, true, 'executed'],
    ['confirm', 'pending', true, 'executed'],
    ['confirm', 'done', true, 'executed'],
    ['confirm', 'weird', false, 'failed'],
    ['cancel', undefined, undefined, 'cancelled'],
    ['cancel', 'pending', true, 'cancelled'],
    ['cancel', 'weird', undefined, 'cancelled'],
  ] as const)('%s status=%s ok=%s -> %s', (verb, status, ok, out) => {
    expect(decisionOutcome(verb, { status: status as never, ok })).toBe(out);
  });

  it('no status and no ok on confirm: unknown (the store checks instead of guessing)', () => {
    expect(decisionOutcome('confirm', { status: undefined as never })).toBeNull();
    expect(decisionOutcome('confirm', { status: 'pending' })).toBeNull();
    expect(decisionOutcome('confirm', { status: 'weird' })).toBeNull();
  });
});

describe('deriveCrmView', () => {
  const open = { status: 'open' as const };
  const pending = crmState();

  it('no CRM yet: the add button; dismissed items hide it', () => {
    expect(deriveCrmView({ ...open, crm: null }, undefined, undefined)).toEqual({ kind: 'idle', note: null });
    expect(deriveCrmView({ status: 'dismissed', crm: null }, undefined, undefined)).toEqual({ kind: 'hidden' });
    // Eski server `crm` maydonini umuman bermaydi.
    expect(deriveCrmView({ ...open }, undefined, undefined)).toEqual({ kind: 'idle', note: null });
  });

  it('a running request or a local reply wins over the stored state', () => {
    expect(deriveCrmView({ ...open, crm: pending }, { kind: 'requesting', startedAt: 1 }, undefined)).toEqual({ kind: 'requesting', startedAt: 1 });
    expect(deriveCrmView({ ...open, crm: null }, { kind: 'answered', text: 'Qaysi loyiha?' }, undefined).kind).toBe('answered');
    expect(deriveCrmView({ ...open, crm: null }, { kind: 'failed', reason: 'crm_not_connected' }, undefined)).toEqual({
      kind: 'failed',
      reason: 'crm_not_connected',
    });
  });

  it('persisted pending -> a live proposal card', () => {
    const v = deriveCrmView({ ...open, crm: pending }, undefined, undefined);
    expect(v).toMatchObject({ kind: 'proposal', outcome: 'pending', session: null });
  });

  it('persisted executed -> compact "added" with the CRM key; confirmed in this session -> the card with success', () => {
    const done: ActionCrm = { ...pending, status: 'executed', result: { key: 'DVSIB-231' } };
    expect(deriveCrmView({ status: 'done', crm: done }, undefined, undefined)).toEqual({ kind: 'added', key: 'DVSIB-231', link: null });
    const session = { status: 'executed' as const, result: { key: 'DVSIB-231' }, error: null };
    expect(deriveCrmView({ ...open, crm: pending }, undefined, session)).toMatchObject({ kind: 'proposal', outcome: 'executed', session });
  });

  it('cancelled -> the add button again (with a note); expired/failed -> the card in its final state', () => {
    expect(deriveCrmView({ ...open, crm: { ...pending, status: 'cancelled' } }, undefined, undefined)).toEqual({ kind: 'idle', note: 'cancelled' });
    expect(deriveCrmView({ ...open, crm: pending }, undefined, { status: 'cancelled', result: null, error: null })).toEqual({ kind: 'idle', note: 'cancelled' });
    expect(deriveCrmView({ ...open, crm: { ...pending, status: 'expired' } }, undefined, undefined)).toMatchObject({ kind: 'proposal', outcome: 'expired' });
    expect(deriveCrmView({ ...open, crm: { ...pending, status: 'failed' } }, undefined, undefined)).toMatchObject({ kind: 'proposal', outcome: 'failed' });
  });

  it('a lost reply is superseded by a proposal the server stored meanwhile (new token)', () => {
    const lost = { kind: 'failed' as const, reason: 'gateway_timeout', prevToken: null };
    expect(deriveCrmView({ ...open, crm: pending }, lost, undefined)).toMatchObject({ kind: 'proposal', outcome: 'pending' });
    expect(deriveCrmView({ ...open, crm: null }, lost, undefined)).toEqual(lost);
    const replaced = { kind: 'failed' as const, reason: 'timeout', prevToken: 'tok-old' };
    expect(deriveCrmView({ ...open, crm: pending }, replaced, undefined)).toMatchObject({ kind: 'proposal' });
    const same = { kind: 'failed' as const, reason: 'timeout', prevToken: 'tok-1' };
    expect(deriveCrmView({ ...open, crm: pending }, same, undefined)).toEqual(same);
    // Server javobi (CRM ulanmagan) - `prevToken` yo'q, saqlangan holatdan ustun.
    expect(deriveCrmView({ ...open, crm: pending }, { kind: 'failed', reason: 'crm_not_connected' }, undefined).kind).toBe('failed');
  });

  it('server "executed" wins over a phone-side "expired" / "unknown" (never invite a duplicate)', () => {
    const done: ActionCrm = { ...pending, status: 'executed', result: { key: 'DVSIB-231' } };
    for (const status of ['expired', 'unknown'] as const) {
      expect(deriveCrmView({ ...open, crm: done }, undefined, { status, result: null, error: null })).toEqual({ kind: 'added', key: 'DVSIB-231', link: null });
    }
    // Telefondagi "bajarilmadi" (ok === false) esa o'z holicha qoladi.
    expect(deriveCrmView({ ...open, crm: done }, undefined, { status: 'failed', result: null, error: 'x' })).toMatchObject({ kind: 'proposal', outcome: 'failed' });
    expect(deriveCrmView({ ...open, crm: pending }, undefined, { status: 'unknown', result: null, error: null })).toMatchObject({ kind: 'proposal', outcome: 'unknown' });
  });

  it('crmFromProposal builds a pending state from a bare proposal', () => {
    const p = crmProposal();
    expect(crmFromProposal(p)).toEqual({ token: p.token, status: 'pending', proposal: p, expiresAt: p.expires_at, result: null, updatedAt: null });
  });
});
