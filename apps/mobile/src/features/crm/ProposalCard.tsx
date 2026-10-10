/**
 * Barno (v3) TAKLIF qilgan CRM o'zgarishi - Mini App'dagi `ProposalCard.vue` va web
 * `ActionCard.vue` ning native nusxasi. HECH NARSA O'ZGARMAGAN: CRM ga yozish faqat
 * "Tasdiqlash" bosilganda (`/api/v1/actions/{token}/confirm` - chatdagi AYNI yo'l).
 *
 * Tarkib: tizim nomi va "Taklif qilingan o'zgarish", qolgan vaqt (pill), xulosa,
 * obyekt va o'zgarishlar "yorliq: qiymat" qatorlarida (eski qiymat ustidan chizilgan),
 * ogohlantirishlar, ikki KATTA tugma (bosh barmoq ostida, teng kenglikda).
 *
 * Muddat telefon soatida tugasa karta o'zi yakunlanadi ("Muddati tugagan"): server
 * baribir 410 qaytaradi - tugmani bosib xato o'qish shart emas. Yakuniy holatda
 * tugmalar o'rnida natija qoladi; muddati o'tgan / bajarilmagan / natija noma'lum
 * bo'lsa - "Yangi taklif olish".
 *
 * Band paytida tugmada faqat aylana (tor ekranda "Bajarilmoqda..." kesilib qolardi),
 * nima bo'layotgani esa tugmalar ustidagi bitta qatorda.
 */
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import type { ActionCrm, ActionProposal } from '@/api/types';
import { useT } from '@/features/settings/settingsStore';
import type { TFn, TKey } from '@/i18n';
import { Button } from '@/ui/components';
import { errorKey } from '@/ui/errors';
import { useTheme } from '@/ui/theme';

import type { Busy } from './crmStore';
import {
  expiresAtMs,
  isCreateOperation,
  proposalRows,
  proposalWarnings,
  resultKey,
  resultLink,
  timeLeftText,
  type Outcome,
  type SessionOutcome,
} from './proposalModel';
import { useNow } from './useNow';

/** Server tasdiqni rad etdi (400/422 "Taklifni bajarib bo'lmadi") - kod emas, tushunarli matn. */
const REJECTED = new Set(['bad_request', 'validation_error']);

/** Uzun qiymat (tavsif) - yorliq ustida, chapdan: o'ngga tekislangan uzun paragraf o'qilmaydi. */
const LONG_VALUE = 40;

const BUSY_KEYS: Record<Busy, TKey> = { confirm: 'crm.confirming', cancel: 'crm.cancelling', check: 'crm.checking' };

/** Tasdiqlash / rad etish xatosi -> tushunarli matn. Noma'lum kod ko'rsatilmaydi. */
export function actionErrorText(t: TFn, code: string): string {
  if (REJECTED.has(code)) return t('crm.failedActionHint');
  if (code === 'unverified') return t('crm.unverified');
  const key = errorKey(code);
  return key ? t(key) : t('common.error');
}

/** CRM havolasi brauzerda (yoki CRM ilovasida). Ochadigan ilova bo'lmasa - jim. */
export function openExternalLink(url: string): void {
  Promise.resolve()
    .then(() => Linking.openURL(url))
    .catch(() => {});
}

export interface ProposalCardProps {
  /** testID qo'shimchasi (vazifa id). */
  id: string;
  proposal: ActionProposal;
  crm: ActionCrm;
  outcome: Outcome;
  session: SessionOutcome | null;
  busy?: Busy;
  actionError?: string;
  /** Oldingi tasdiq javobi yo'qolgan - natija hali aniq emas. */
  unsure?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onResend: () => void;
}

export function ProposalCard(props: ProposalCardProps) {
  const { id, proposal, crm, outcome, session, busy, unsure } = props;
  const t = useT();
  const th = useTheme();
  const expiresAt = expiresAtMs(proposal.expires_at ?? crm.expiresAt);
  // Muddat telefon soatida o'tdi - `timedOut`; taymer shundan keyin o'zi to'xtaydi. Tasdiq
  // so'rovi ketayotganda karta yakunlanmaydi - natijani server aytadi (410 yoki bajarildi).
  const now = useNow(outcome === 'pending' && expiresAt !== null, expiresAt);
  const left = expiresAt !== null ? expiresAt - now : Infinity;
  const timedOut = outcome === 'pending' && !busy && left <= 0;
  // Javobi yo'qolgan tasdiqdan keyin muddat o'tsa - "muddati tugagan" emas: bajarilgan bo'lishi mumkin.
  const state: Outcome = timedOut ? (unsure ? 'unknown' : 'expired') : outcome;
  const settled = state !== 'pending';

  const rows = proposalRows(proposal, t);
  const warnings = proposalWarnings(proposal);
  const platform = (proposal.connector || '').toUpperCase();
  const pill = !settled && expiresAt !== null ? timeLeftText(left, t) : '';
  const result = session?.result ?? crm.result;
  const key = state === 'executed' ? resultKey(result) : '';
  const link = state === 'executed' ? resultLink(result) : null;

  const tone =
    state === 'executed' ? th.tones.good : state === 'expired' || state === 'unknown' ? th.tones.warn : state === 'failed' ? th.tones.bad : th.tones.neutral;
  const outcomeLabel =
    state === 'executed'
      ? t('crm.done')
      : state === 'expired'
        ? t('crm.expired')
        : state === 'failed'
          ? t('crm.failedAction')
          : state === 'cancelled'
            ? t('crm.cancelled')
            : state === 'unknown'
              ? t('crm.unknown')
              : '';
  const eyebrow = isCreateOperation(proposal.operation) ? t('crm.proposedNew') : t('crm.proposed');

  // Ildizga accessibilityLabel YO'Q: TalkBack kartaning matnini (xulosa, qatorlar, ogohlantirish)
  // tasdiqdan oldin o'qishi kerak - umumiy yorliq ularni yashirib qo'yardi.
  return (
    <View testID={`crm-card-${id}`} style={[s.card, { borderColor: state === 'executed' ? tone.fg : th.border, backgroundColor: th.bg }]}>
      <View style={s.meta}>
        <View style={[s.glyph, { backgroundColor: th.surfaceAlt }]}>
          <Text style={{ color: th.textMuted, fontSize: 15 }}>✎</Text>
        </View>
        <Text numberOfLines={1} style={[s.eyebrow, { color: th.textMuted }]}>
          {[platform, eyebrow].filter(Boolean).join(' · ')}
        </Text>
        {pill ? (
          <View style={[s.pill, { backgroundColor: left < 60_000 ? th.tones.warn.bg : th.surfaceAlt }]}>
            <Text testID={`crm-countdown-${id}`} style={[s.pillText, { color: left < 60_000 ? th.tones.warn.fg : th.text }]}>
              {pill}
            </Text>
          </View>
        ) : null}
      </View>
      <Text style={[s.title, { color: th.text }, settled && state !== 'executed' && { color: th.textMuted }]}>
        {proposal.summary || t('crm.proposed')}
      </Text>

      {rows.length ? (
        <View style={[s.rows, { borderColor: th.border }]}>
          {rows.map((r, i) => {
            const stacked = r.to.length > LONG_VALUE || (r.from?.length ?? 0) > LONG_VALUE;
            return (
              <View key={i} style={[stacked ? s.rowStacked : s.row, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderColor: th.border }]}>
                <Text style={[stacked ? s.rowLabelStacked : s.rowLabel, { color: th.textMuted }]}>{r.label}</Text>
                <Text style={[stacked ? s.rowValueStacked : s.rowValue, { color: th.text }]}>
                  {r.from ? (
                    <Text style={{ color: th.textMuted, textDecorationLine: 'line-through' }}>{r.from}</Text>
                  ) : null}
                  {r.from ? ' → ' : ''}
                  <Text style={s.bold}>{r.to}</Text>
                </Text>
              </View>
            );
          })}
        </View>
      ) : null}

      {warnings.length ? (
        <View style={[s.warn, { backgroundColor: th.tones.warn.bg }]}>
          {warnings.map((w, i) => (
            <Text key={i} style={[s.warnText, { color: th.tones.warn.fg }]}>
              ⚠ {w}
            </Text>
          ))}
        </View>
      ) : null}

      {props.actionError && !settled && !busy ? (
        <Text accessibilityRole="alert" testID={`crm-error-${id}`} style={[s.small, { color: th.tones.bad.fg }]}>
          {actionErrorText(t, props.actionError)}
        </Text>
      ) : null}
      {unsure && !settled && !busy ? (
        <Text testID={`crm-unsure-${id}`} style={[s.small, { color: th.textMuted }]}>
          {t('crm.unsureHint')}
        </Text>
      ) : null}

      {settled ? (
        <View testID={`crm-outcome-${id}`} accessibilityLiveRegion="polite" style={s.outcome}>
          <View style={[s.dot, { backgroundColor: tone.bg }]}>
            <Text style={{ color: tone.fg, fontWeight: '800', fontSize: 12 }}>{state === 'executed' ? '✓' : '✕'}</Text>
          </View>
          <Text style={[s.outcomeText, { color: th.text }]}>{outcomeLabel}</Text>
          {key ? <Text style={[s.key, { color: th.textMuted }]}>{key}</Text> : null}
        </View>
      ) : null}
      {state === 'executed' && link ? (
        <Button small variant="ghost" title={t('crm.openLink')} testID={`crm-link-${id}`} style={s.leftBtn} onPress={() => openExternalLink(link)} />
      ) : null}
      {state === 'expired' ? <Text style={[s.small, { color: th.textMuted }]}>{t('crm.expiredHint')}</Text> : null}
      {state === 'unknown' ? (
        <Text testID={`crm-unknown-${id}`} style={[s.small, { color: th.tones.warn.fg }]}>
          {t('crm.unknownHint')}
        </Text>
      ) : null}
      {state === 'failed' ? (
        <>
          <Text style={[s.small, { color: th.tones.bad.fg }]}>{t('crm.failedActionHint')}</Text>
          {/* Platformaning o'z matni (inglizcha / texnik bo'lishi mumkin) - faqat ikkinchi, xira qator. */}
          {session?.error ? (
            <Text numberOfLines={3} style={[s.detail, { color: th.textMuted }]}>
              {t('crm.failedActionDetail', { text: session.error })}
            </Text>
          ) : null}
        </>
      ) : null}
      {state === 'expired' || state === 'failed' || state === 'unknown' ? (
        <Button small title={t('crm.newProposal')} testID={`crm-resend-${id}`} style={s.leftBtn} onPress={props.onResend} />
      ) : null}

      {!settled ? (
        <>
          {busy ? (
            <View testID={`crm-busy-line-${id}`} accessibilityLiveRegion="polite" style={s.busyLine}>
              <ActivityIndicator size="small" color={th.primary} />
              <Text style={[s.busyText, { color: th.text }]}>{t(BUSY_KEYS[busy])}</Text>
            </View>
          ) : (
            <Text style={[s.small, { color: th.textMuted }]}>{t('crm.safe')}</Text>
          )}
          <View style={s.buttons}>
            <BigButton
              testID={`crm-cancel-${id}`}
              title={t('crm.cancel')}
              busyLabel={busy === 'cancel' ? t('crm.cancelling') : null}
              disabled={!!busy}
              onPress={props.onCancel}
            />
            <View style={{ width: 8 }} />
            <BigButton
              primary
              testID={`crm-confirm-${id}`}
              title={t('crm.confirm')}
              busyLabel={busy === 'confirm' || busy === 'check' ? t(BUSY_KEYS[busy]) : null}
              disabled={!!busy}
              onPress={props.onConfirm}
            />
          </View>
        </>
      ) : null}
    </View>
  );
}

/**
 * Teng kenglikdagi katta tugma. Band bo'lsa - faqat aylana (matn tugmalar ustidagi qatorda),
 * TalkBack esa to'liq holatni o'qiydi (`busyLabel`).
 */
function BigButton(p: { title: string; primary?: boolean; busyLabel: string | null; disabled: boolean; onPress: () => void; testID: string }) {
  const th = useTheme();
  const fg = p.primary ? th.primaryText : th.text;
  const busy = p.busyLabel != null;
  return (
    <Pressable
      testID={p.testID}
      accessibilityRole="button"
      accessibilityLabel={p.busyLabel ?? p.title}
      accessibilityState={{ disabled: p.disabled, busy }}
      disabled={p.disabled}
      onPress={p.onPress}
      style={({ pressed }) => [
        s.big,
        p.primary ? { backgroundColor: th.primary } : { backgroundColor: th.surfaceAlt, borderWidth: 1, borderColor: th.border },
        { opacity: p.disabled && !busy ? 0.5 : pressed ? 0.85 : 1 },
      ]}>
      {busy ? (
        <ActivityIndicator size="small" color={fg} />
      ) : (
        <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} style={[s.bigText, { color: fg }]}>
          {p.title}
        </Text>
      )}
    </Pressable>
  );
}

const s = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 14, padding: 12, marginTop: 8 },
  meta: { flexDirection: 'row', alignItems: 'center' },
  glyph: { width: 28, height: 28, borderRadius: 8, alignItems: 'center', justifyContent: 'center', marginRight: 8 },
  eyebrow: { flex: 1, fontSize: 12, fontWeight: '600' },
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, marginLeft: 8 },
  pillText: { fontSize: 12, fontWeight: '700', fontVariant: ['tabular-nums'] },
  title: { fontSize: 15, lineHeight: 21, fontWeight: '600', marginTop: 8 },
  rows: { borderTopWidth: StyleSheet.hairlineWidth, borderBottomWidth: StyleSheet.hairlineWidth, marginTop: 10 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8 },
  rowLabel: { fontSize: 13, lineHeight: 18, marginRight: 12, flexShrink: 0, maxWidth: '45%' },
  rowValue: { fontSize: 13, lineHeight: 18, flex: 1, textAlign: 'right' },
  rowStacked: { paddingVertical: 8 },
  rowLabelStacked: { fontSize: 13, lineHeight: 18 },
  rowValueStacked: { fontSize: 13, lineHeight: 19, marginTop: 2 },
  bold: { fontWeight: '600' },
  warn: { borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8, marginTop: 10 },
  warnText: { fontSize: 13, lineHeight: 18 },
  small: { fontSize: 12, lineHeight: 17, marginTop: 8 },
  detail: { fontSize: 11, lineHeight: 15, marginTop: 4 },
  busyLine: { flexDirection: 'row', alignItems: 'center', marginTop: 8 },
  busyText: { fontSize: 13, fontWeight: '600', marginLeft: 8, flex: 1 },
  outcome: { flexDirection: 'row', alignItems: 'center', marginTop: 10 },
  dot: { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 8 },
  outcomeText: { fontSize: 14, fontWeight: '700', flex: 1 },
  key: { fontFamily: 'monospace', fontSize: 13, marginLeft: 8 },
  leftBtn: { alignSelf: 'flex-start', marginTop: 8 },
  buttons: { flexDirection: 'row', marginTop: 10 },
  big: { flex: 1, minHeight: 48, borderRadius: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10 },
  bigText: { fontSize: 15, fontWeight: '700' },
});
