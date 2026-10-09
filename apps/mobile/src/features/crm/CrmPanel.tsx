/**
 * Vazifa ostidagi CRM bloki (yig'ilishning Vazifalar tabi va "Vazifalarim" ekrani):
 *
 *   "CRMga qo'shish"  -> Barno (v3) taklif tayyorlaydi (5-30 s; ekrandan chiqish mumkin)
 *                     -> taklif kartasi: Tasdiqlash / Rad etish, qolgan vaqt
 *                     -> "CRMga qo'shildi" (+ vazifa kaliti, havola bo'lsa)
 *   matnli javob      -> Barno javobi (aniqlik so'radi) + "Qayta yuborish"
 *   CRM ulanmagan     -> qayerda ulashni tushuntirish + "Chatga qaytish" (Mini App)
 *
 * Holat qayerdan - `proposalModel.deriveCrmView`; jarayon - `crmStore` (ekrandan tashqarida).
 *
 * Panel vazifa qatorining OSTIDA, butun kenglikda (`ActionRow` footer): karta tugmalari tor
 * ekranda ham sig'adi. Ixcham holatlar (tugma, "qo'shilgan") vazifa matni bilan bir chiziqda.
 */
import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { AccessibilityInfo, ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import type { ActionItem, Speaker } from '@/api/types';
import { renderTokens } from '@/features/meeting/renderTokens';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { TFn, TKey } from '@/i18n';
import { useServices } from '@/services';
import { Button, styles as ui } from '@/ui/components';
import { errorKey } from '@/ui/errors';
import { MarkdownLite } from '@/ui/markdown';
import { useTheme } from '@/ui/theme';

import { createCrmController, useCrmStore, type CrmController } from './crmStore';
import { openExternalLink, ProposalCard } from './ProposalCard';
import { deriveCrmView } from './proposalModel';
import { useNow } from './useNow';

export function useCrmController(): CrmController {
  const { meetings, actions } = useServices();
  const qc = useQueryClient();
  return useMemo(() => createCrmController({ meetings, actions, qc }), [meetings, actions, qc]);
}

const REASON_KEYS: Record<string, TKey> = {
  assistant_busy: 'crm.fail.busy',
  timeout: 'crm.fail.timeout',
  gateway_timeout: 'crm.fail.timeout',
  assistant_not_configured: 'crm.fail.notConfigured',
  empty: 'crm.fail.empty',
  assistant_unavailable: 'crm.fail.generic',
  assistant_error: 'crm.fail.generic',
};

/** Sabab kodi (server `reason` yoki ApiError kodi) -> do'stona matn. Kod ko'rsatilmaydi. */
export function crmFailureText(t: TFn, reason: string): string {
  const own = REASON_KEYS[reason];
  if (own) return t(own);
  const common = errorKey(reason);
  return common ? t(common) : t('crm.fail.generic');
}

/** Mini App (asosiy ekran) - u har doim stek tagida (`unstable_settings.anchor`). */
function backToChat(): void {
  try {
    router.dismissTo('/');
  } catch {
    router.navigate('/');
  }
}

export function CrmPanel({ item, speakers }: { item: ActionItem; speakers?: Speaker[] }) {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((st) => st.uiLang);
  const ctrl = useCrmController();
  const token = item.crm?.token ?? '';
  const local = useCrmStore((st) => st.local[item.id]);
  const session = useCrmStore((st) => (token ? st.settled[token] : undefined));
  const busy = useCrmStore((st) => (token ? st.busy[token] : undefined));
  const actionError = useCrmStore((st) => (token ? st.actionError[token] : undefined));
  const unsure = useCrmStore((st) => (token ? !!st.unsure[token] : false));
  const view = deriveCrmView(item, local, session);
  const ref = { id: item.id, meetingId: item.meetingId };
  const id = item.id;

  switch (view.kind) {
    case 'hidden':
      return null;

    case 'idle':
      return (
        <View style={[s.panel, s.indent]}>
          {view.note === 'cancelled' ? <Text style={[s.note, { color: th.textMuted }]}>{t('crm.cancelled')}</Text> : null}
          <Button
            small
            variant="secondary"
            testID={`crm-add-${id}`}
            title={t('crm.add')}
            style={s.left}
            onPress={() => void ctrl.request(ref, { force: !!item.crm })}
          />
        </View>
      );

    case 'requesting':
      return <Requesting id={id} startedAt={view.startedAt} />;

    case 'answered':
      return (
        <View testID={`crm-answer-${id}`} style={[s.box, { borderColor: th.border, backgroundColor: th.bg }]}>
          <Text style={[s.eyebrow, { color: th.textMuted }]}>{t('crm.answered')}</Text>
          <MarkdownLite text={renderTokens(view.text, speakers ?? [], lang)} style={{ marginTop: 6 }} />
          <Text style={[s.note, { color: th.textMuted }]}>{t('crm.answeredHint')}</Text>
          <View style={[ui.row, s.actions]}>
            <Button small variant="ghost" title={t('common.close')} testID={`crm-dismiss-${id}`} onPress={() => ctrl.dismiss(ref)} />
            <Button small title={t('crm.resend')} testID={`crm-resend-${id}`} style={{ marginLeft: 8 }} onPress={() => void ctrl.request(ref, { force: true })} />
          </View>
        </View>
      );

    case 'failed':
      if (view.reason === 'crm_not_connected') {
        return (
          <View testID={`crm-failed-${id}`} style={[s.box, { borderColor: th.tones.warn.bg, backgroundColor: th.tones.warn.bg }]}>
            <Text style={[s.title, { color: th.tones.warn.fg }]}>{t('crm.notConnectedTitle')}</Text>
            <Text style={[s.body, { color: th.tones.warn.fg }]}>{t('crm.notConnected')}</Text>
            <View style={[ui.row, s.actions]}>
              <Button small title={t('crm.openChat')} testID={`crm-open-chat-${id}`} onPress={backToChat} />
              <Button small variant="ghost" title={t('common.retry')} testID={`crm-retry-${id}`} style={{ marginLeft: 8 }} onPress={() => void ctrl.request(ref)} />
            </View>
          </View>
        );
      }
      // Qayta urinish `force` SIZ: javob yo'qolgan (504) bo'lsa, server saqlagan taklif darhol
      // qaytadi - v3 ga qayta 2 daqiqa kutilmaydi va soatlik limit sarflanmaydi.
      return (
        <View testID={`crm-failed-${id}`} style={[s.box, { borderColor: th.tones.bad.bg, backgroundColor: th.tones.bad.bg }]}>
          <Text style={[s.body, { color: th.tones.bad.fg }]}>{crmFailureText(t, view.reason)}</Text>
          <View style={[ui.row, s.actions]}>
            <Button small title={t('common.retry')} testID={`crm-retry-${id}`} onPress={() => void ctrl.request(ref)} />
            <Button small variant="ghost" title={t('common.close')} testID={`crm-dismiss-${id}`} style={{ marginLeft: 8 }} onPress={() => ctrl.dismiss(ref)} />
          </View>
        </View>
      );

    case 'proposal':
      return (
        <ProposalCard
          key={view.crm.token}
          id={id}
          proposal={view.proposal}
          crm={view.crm}
          outcome={view.outcome}
          session={view.session}
          busy={busy}
          actionError={actionError}
          unsure={unsure}
          onConfirm={() => void ctrl.confirm(ref, view.crm.token)}
          onCancel={() => void ctrl.cancel(ref, view.crm.token)}
          onResend={() => void ctrl.request(ref, { force: true })}
        />
      );

    case 'added': {
      const link = view.link;
      return (
        <View testID={`crm-added-${id}`} style={[ui.row, s.panel, s.indent, { flexWrap: 'wrap' }]}>
          <View style={[s.added, { backgroundColor: th.tones.good.bg }]}>
            <Text style={[s.addedText, { color: th.tones.good.fg }]}>
              ✓ {t('crm.added')}
              {view.key ? ` · ${view.key}` : ''}
            </Text>
          </View>
          {link ? (
            <Button small variant="ghost" title={t('crm.openLink')} testID={`crm-link-${id}`} style={{ marginLeft: 8 }} onPress={() => openExternalLink(link)} />
          ) : null}
        </View>
      );
    }
  }
}

/**
 * Kutish holati: aylana, nima bo'layotgani, o'tgan soniyalar - va chiqish xavfsiz ekani.
 * TalkBack bir marta aytadi: soniya hisoblagichi live region'da bo'lsa, har soniyada
 * qaytadan o'qilardi (150 s gacha).
 */
function Requesting({ id, startedAt }: { id: string; startedAt: number }) {
  const t = useT();
  const th = useTheme();
  const now = useNow(true);
  const sec = Math.max(0, Math.floor((now - startedAt) / 1000));
  const title = t('crm.requesting');
  useEffect(() => {
    try {
      AccessibilityInfo.announceForAccessibility(title);
    } catch {
      /* ekran o'quvchi yo'q - muhim emas */
    }
  }, [title]);
  return (
    <View testID={`crm-busy-${id}`} style={[s.box, { borderColor: th.border, backgroundColor: th.bg }]}>
      <View style={ui.row}>
        <ActivityIndicator size="small" color={th.primary} />
        <Text style={[s.title, s.busyTitle, { color: th.text }]}>{title}</Text>
        <Text
          importantForAccessibility="no"
          accessibilityElementsHidden
          style={[s.elapsed, { color: th.textMuted }]}>
          {t('crm.elapsed', { n: sec })}
        </Text>
      </View>
      <Text style={[s.note, { color: th.textMuted }]}>{t('crm.requestingHint')}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  panel: { marginTop: 8 },
  /** Belgi katagi (24) + oraliq (10): ixcham holatlar vazifa matni bilan bir chiziqda. */
  indent: { marginLeft: 34 },
  left: { alignSelf: 'flex-start' },
  note: { fontSize: 12, lineHeight: 17, marginTop: 6 },
  box: { borderWidth: 1, borderRadius: 14, padding: 12, marginTop: 8 },
  eyebrow: { fontSize: 12, fontWeight: '600' },
  title: { fontSize: 14, fontWeight: '700' },
  busyTitle: { flex: 1, marginLeft: 10 },
  body: { fontSize: 13, lineHeight: 19, marginTop: 4 },
  elapsed: { fontSize: 12, fontVariant: ['tabular-nums'], marginLeft: 8 },
  actions: { marginTop: 10, flexWrap: 'wrap' },
  added: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  addedText: { fontSize: 13, fontWeight: '700' },
});
