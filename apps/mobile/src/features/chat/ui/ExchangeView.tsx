/**
 * Bitta savol-javob (Mini App `Exchange.vue` kabi):
 *
 *   o'ngda   savol pufakchasi
 *   chapda   javob (Markdown, butun kenglikda), oqim paytida bosqich matni yoki
 *            "O'ylayapman…" va oxirida kursor
 *   ostida   manbalar tugmasi, ariza (DOCX/PDF), CRM taklifi kartasi, amallar
 *            (🔊 tinglash, nusxalash, qayta javob)
 *
 * Jonli ovozli rejimda berilgan savol pufakchasida kichik 🎤 belgisi bor - chatni keyin
 * o'qigan odam savol aytilganini (matni nutqdan tanilganini) bilsin.
 *
 * Xato: xizmat matni + "Qayta urinish"; HRM/CRM ulanmagan bo'lsa - "Qayta ulash"
 * (qayta kirish, ulanish yangilanadi).
 */
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { Copy, FileText, Mic, RotateCcw } from 'lucide-react-native';
import { memo, useMemo, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import type { AnswerSource, ChatApi } from '@/api/chat';
import type { ActionsApi } from '@/api/actions';
import { isExpiredError } from '@/api/actions';
import { ApiError } from '@/api/client';
import { isAuthCode, type Exchange } from '@/features/chat/chatStore';
import { sourceMarks } from '@/features/chat/sources';
import { ProposalCard } from '@/features/crm/ProposalCard';
import { crmFromProposal, decisionOutcome, type Outcome, type SessionOutcome } from '@/features/crm/proposalModel';
import type { Busy } from '@/features/crm/crmStore';
import { useSettings, useT } from '@/features/settings/settingsStore';
// Chat ekrani: barrel (`@/features/voice`) EMAS - u expo-router hook'larini olib keladi.
import { canReadAloud } from '@/features/voice/readAloud';
import { ListenButton } from '@/features/voice/ui/ListenButton';
import { errorText, showToast } from '@/ui/errors';
import { useTheme, type Theme } from '@/ui/theme';

import { AnswerMarkdown } from './AnswerMarkdown';

export interface ExchangeViewProps {
  ex: Exchange;
  api: ChatApi;
  actions: ActionsApi;
  live: boolean;
  onRetry: (id: string) => void;
  onReconnect: () => void;
  onSources: (sources: AnswerSource[], focus?: string) => void;
}

function ExchangeViewImpl({ ex, api, actions, live, onRetry, onReconnect, onSources }: ExchangeViewProps) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const uiLang = useSettings((x) => x.uiLang);
  const streaming = ex.status === 'streaming' || (ex.status === 'pending' && live);
  const waiting = ex.status === 'pending' && !ex.answer;
  // Ovoz faqat o'zbekcha (server ovozi lotin o'zbekcha) - aks holda tugma umuman yo'q.
  const listenable = useMemo(() => ex.status === 'done' && !!ex.answer && canReadAloud(ex.answer, uiLang), [ex.status, ex.answer, uiLang]);
  const voiceQ = ex.input === 'voice';
  // "N manba" tugmasida manbalar belgilari (HRM odamlar, DWH ombor, hujjat kitob) - qaysi
  // tizimdan javob berilgani tugmani ochmasdan ko'rinsin (Claude'dagi favicon qatori kabi).
  const marks = useMemo(() => sourceMarks(ex.sources), [ex.sources]);

  const copy = async () => {
    try {
      await Clipboard.setStringAsync(ex.answer);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      showToast(t('chat.copied'));
    } catch {
      /* nusxalab bo'lmadi */
    }
  };

  const onCite = (marker: string) => {
    if (ex.sources.length) onSources(ex.sources, marker);
  };

  const openArtifact = async (path: string | null | undefined, kind: 'docx' | 'pdf') => {
    if (!path) return;
    try {
      const name = `${(ex.artifact?.title || 'hujjat').slice(0, 60)}.${kind}`;
      const link = await api.artifactLink(path, name);
      await Linking.openURL(api.absolute(link.url));
    } catch (err) {
      showToast(err instanceof ApiError ? errorText(t, err) : t('chat.openFailed'));
    }
  };

  return (
    <View style={s.wrap}>
      {ex.question ? (
        <View style={s.qRow}>
          <View
            style={[s.bubble, voiceQ ? s.voiceBubble : null]}
            testID={voiceQ ? 'question-voice' : undefined}
            accessible={voiceQ ? true : undefined}
            accessibilityLabel={voiceQ ? `${t('nav.voice.voiceQuestion')}: ${ex.question}` : undefined}>
            {voiceQ ? <Mic size={14} color={th.textMuted} strokeWidth={2} style={s.voiceMark} /> : null}
            <Text style={[s.qText, voiceQ ? s.voiceText : null]} selectable>
              {ex.question}
            </Text>
          </View>
        </View>
      ) : null}

      <View style={s.answer}>
        {waiting ? (
          <View style={s.thinking} accessibilityLiveRegion="polite">
            <ActivityIndicator size="small" color={th.brand} />
            <Text style={s.thinkingText} numberOfLines={2}>
              {ex.stage || t('chat.thinking')}
            </Text>
          </View>
        ) : null}

        {ex.answer ? <AnswerMarkdown text={ex.answer} streaming={streaming} onCite={onCite} /> : null}

        {ex.status === 'error' && ex.error ? (
          <View style={s.errorBox} accessibilityRole="alert">
            <Text style={s.errorText}>{ex.error}</Text>
            {isAuthCode(ex.errorCode) ? (
              <Pressable onPress={onReconnect} style={s.errorBtn} accessibilityRole="button">
                <Text style={s.errorBtnText}>{t('chat.reconnect')}</Text>
              </Pressable>
            ) : ex.question ? (
              <Pressable onPress={() => onRetry(ex.id)} style={s.errorBtn} accessibilityRole="button">
                <Text style={s.errorBtnText}>{t('chat.retry')}</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {ex.status === 'stopped' ? <Text style={s.note}>{t('chat.stopped')}</Text> : null}
        {ex.status === 'cancelled' && ex.question && live ? <Text style={s.note}>{t('chat.cancelled')}</Text> : null}
        {ex.warning && ex.status === 'done' ? <Text style={s.note}>⚠ {t('chat.warning')}</Text> : null}

        {ex.artifact && (ex.artifact.docx_url || ex.artifact.pdf_url) ? (
          <View style={s.artifact}>
            <View style={s.artifactHead}>
              <FileText size={18} color={th.brand} strokeWidth={2} />
              <Text style={s.artifactTitle} numberOfLines={2}>
                {ex.artifact.title || t('chat.artifactReady')}
              </Text>
            </View>
            <View style={s.artifactBtns}>
              {ex.artifact.docx_url ? (
                <Pressable style={s.chip} onPress={() => void openArtifact(ex.artifact?.docx_url, 'docx')} accessibilityRole="button">
                  <Text style={s.chipText}>{t('chat.artifactWord')}</Text>
                </Pressable>
              ) : null}
              {ex.artifact.pdf_url ? (
                <Pressable style={s.chip} onPress={() => void openArtifact(ex.artifact?.pdf_url, 'pdf')} accessibilityRole="button">
                  <Text style={s.chipText}>{t('chat.artifactPdf')}</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        {ex.proposal ? <ChatProposal key={ex.proposal.token} ex={ex} actions={actions} onResend={() => onRetry(ex.id)} /> : null}

        {ex.status === 'done' && (ex.answer || ex.sources.length) ? (
          <View style={s.actions}>
            {ex.sources.length ? (
              <Pressable testID="answer-sources" style={s.sourcesBtn} onPress={() => onSources(ex.sources)} accessibilityRole="button" hitSlop={6}>
                <View style={s.sourceMarks}>
                  {marks.map(({ key, Icon }) => (
                    <Icon key={key} size={15} color={th.textSoft} strokeWidth={2} />
                  ))}
                </View>
                <Text style={s.sourcesText}>{t('chat.sources', { n: ex.sources.length })}</Text>
              </Pressable>
            ) : null}
            <View style={{ flex: 1 }} />
            {listenable ? <ListenButton id={ex.id} markdown={ex.answer} turnId={ex.turnId} /> : null}
            {ex.answer ? (
              <Pressable onPress={() => void copy()} accessibilityRole="button" accessibilityLabel={t('chat.copy')} hitSlop={8} style={s.iconBtn}>
                <Copy size={17} color={th.textMuted} strokeWidth={1.9} />
              </Pressable>
            ) : null}
            {ex.question ? (
              <Pressable onPress={() => onRetry(ex.id)} accessibilityRole="button" accessibilityLabel={t('chat.regenerate')} hitSlop={8} style={s.iconBtn}>
                <RotateCcw size={17} color={th.textMuted} strokeWidth={1.9} />
              </Pressable>
            ) : null}
          </View>
        ) : null}
      </View>
    </View>
  );
}

export const ExchangeView = memo(ExchangeViewImpl);

/** Chatdagi CRM/HRM taklifi: yig'ilishlardagi karta bilan bir xil, holati shu yerda. */
function ChatProposal({ ex, actions, onResend }: { ex: Exchange; actions: ActionsApi; onResend: () => void }) {
  const proposal = ex.proposal!;
  const crm = useMemo(() => crmFromProposal(proposal), [proposal]);
  const [outcome, setOutcome] = useState<Outcome>('pending');
  const [busy, setBusy] = useState<Busy | undefined>(undefined);
  const [actionError, setActionError] = useState<string | undefined>(undefined);
  const [session, setSession] = useState<SessionOutcome | null>(null);
  const [unsure, setUnsure] = useState(false);

  const decide = async (verb: 'confirm' | 'cancel') => {
    if (busy) return;
    setBusy(verb);
    setActionError(undefined);
    try {
      const res = verb === 'confirm' ? await actions.confirm(proposal.token) : await actions.cancel(proposal.token);
      const next = decisionOutcome(verb, res) ?? 'unknown';
      setOutcome(next);
      setSession({ status: next, result: res.result ?? null, error: res.error ?? null });
      void Haptics.notificationAsync(next === 'executed' ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Warning).catch(() => {});
    } catch (err) {
      if (isExpiredError(err)) {
        setOutcome(unsure ? 'unknown' : 'expired');
      } else if (err instanceof ApiError && (err.isNetwork || err.status === 502 || err.status === 504)) {
        // Javob yo'qoldi - bajarilgan bo'lishi mumkin: ikkinchi bosish avval holatni tekshiradi.
        setUnsure(true);
        setActionError(err.code);
      } else {
        setActionError(err instanceof ApiError ? err.code : 'internal');
      }
    } finally {
      setBusy(undefined);
    }
  };

  const confirm = async () => {
    if (unsure) {
      setBusy('check');
      try {
        const st = await actions.get(proposal.token);
        if (st.status && st.status !== 'pending') {
          const next = decisionOutcome('confirm', st) ?? 'unknown';
          setOutcome(next);
          setSession({ status: next, result: st.result ?? null, error: st.error ?? null });
          setBusy(undefined);
          return;
        }
      } catch {
        /* tekshirib bo'lmadi - oddiy tasdiq */
      }
      setBusy(undefined);
    }
    await decide('confirm');
  };

  return (
    <View style={{ marginTop: 8 }}>
      <ProposalCard
        id={ex.id}
        proposal={proposal}
        crm={crm}
        outcome={outcome}
        session={session}
        busy={busy}
        actionError={actionError}
        unsure={unsure}
        onConfirm={() => void confirm()}
        onCancel={() => void decide('cancel')}
        onResend={onResend}
      />
    </View>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    wrap: { paddingHorizontal: 16, paddingTop: 14 },
    qRow: { flexDirection: 'row', justifyContent: 'flex-end', marginBottom: 14 },
    bubble: { maxWidth: '86%', backgroundColor: th.bubble, borderRadius: 20, borderBottomRightRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
    qText: { color: th.text, fontSize: 16, lineHeight: 23 },
    voiceBubble: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
    voiceMark: { marginTop: 5 },
    voiceText: { flexShrink: 1 },
    answer: { minHeight: 8 },
    thinking: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6 },
    thinkingText: { color: th.textMuted, fontSize: 15, flex: 1 },
    errorBox: { borderRadius: 14, backgroundColor: th.tones.bad.bg, padding: 12, gap: 10 },
    errorText: { color: th.tones.bad.fg, fontSize: 15, lineHeight: 21 },
    errorBtn: { alignSelf: 'flex-start', borderRadius: 999, backgroundColor: th.surface, paddingHorizontal: 14, paddingVertical: 8 },
    errorBtnText: { color: th.text, fontWeight: '600', fontSize: 14 },
    note: { color: th.textMuted, fontSize: 13, marginTop: 4 },
    artifact: { marginTop: 6, borderWidth: 1, borderColor: th.border, borderRadius: 16, padding: 12, gap: 10, backgroundColor: th.surface },
    artifactHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    artifactTitle: { color: th.text, fontSize: 15, fontWeight: '600', flex: 1 },
    artifactBtns: { flexDirection: 'row', gap: 8 },
    chip: { borderRadius: 999, backgroundColor: th.surfaceAlt, paddingHorizontal: 14, paddingVertical: 8 },
    chipText: { color: th.text, fontWeight: '600', fontSize: 14 },
    actions: { flexDirection: 'row', alignItems: 'center', marginTop: 6, gap: 4 },
    sourcesBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: 999, backgroundColor: th.surfaceAlt, paddingHorizontal: 12, paddingVertical: 7 },
    sourcesText: { color: th.textSoft, fontSize: 13, fontWeight: '600' },
    sourceMarks: { flexDirection: 'row', alignItems: 'center', gap: 3 },
    iconBtn: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center', borderRadius: 18 },
  });
}
