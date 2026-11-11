/**
 * Chat tabi: BITTA yozuv bo'yicha Barno bilan suhbat (javobni server Claude bilan yozadi).
 * Javob faqat shu yozuv matni, xulosasi va suhbatning oldingi qismiga tayanadi - "batafsilroq",
 * "u kim edi?" kabi davomli savollar ishlaydi. Egasining suhbati kanaldan qat'i nazar bitta: Telegram'da
 * shu yozuv bo'yicha berilgan savollar ham shu yerda ko'rinadi. Slack'da (umumiy hisob) har odamning
 * suhbati alohida - server ularni bu yerga bermaydi. Boshqa yozuvlar hech qachon aralashmaydi.
 *
 *   tepada   "Yangi suhbat" (faqat savol-javob bo'lsa; tasdiq bilan - eskisi arxivlanadi)
 *   o'rtada  savol-javoblar eskidan yangiga: savol o'ngda (brend rangi), javob chapda (Markdown,
 *            `[S1]` -> ism), manba chiplari (▶ vaqt -> pleer; kim va qisqa iqtibos) va FAQAT oxirgi
 *            javob ostida keyingi savol takliflari
 *   pastda   yozish maydoni (1000 belgigacha) - pleer ustida; klaviatura ochilsa uning ustida
 *
 * Yuborish optimistik: savol darhol ko'rinadi va "Barno yozmoqda…"; javob kelgach server qatori
 * bilan almashadi; xato bo'lsa savol joyida qoladi - sababi va "Qayta yuborish". Har xabar o'z
 * kaliti (`clientId`) bilan ketadi va "Qayta yuborish" O'SHA kalitni yuboradi - server shu
 * savol-javobni qaytaradi, takror yaratmaydi. Javob yo'lda yo'qolib (tarmoq, proksi 504, kutish
 * vaqti), server esa uni saqlagan bo'lsa - tarix qayta o'qilganda shu kalitli savol-javob keladi va
 * xato (yoki kutish) yo'qoladi; javobi noma'lum xatodan keyin tarix ~8 s dan so'ng yana bir marta
 * o'qiladi. Holat global mutatsiya keshida (`useChatOutgoing`): tab almashsa ham yo'qolmaydi va
 * javob kutilayotganda ikkinchi xabar yuborilmaydi.
 *
 * Yozuv o'chirilgan yoki begona (istalgan chat so'rovida `not_found` kodli 404): "Yozuv topilmadi",
 * chat yopiladi (yozish ham, qayta yuborish ham yo'q) va yozuv so'rovi qayta o'qiladi.
 *
 * NIMA UCHUN umumiy ScrollView ichida emas (transkript kabi o'z konteyneri): yozish maydoni
 * pastda qotib turadi, ro'yxat esa uning ustida o'zi aylanadi. Ko'rinish asosiy chatdan
 * (`features/chat/ui`): savol pufakchasi, yozish kartasi, xato qutisi.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ArrowUp, MessagesSquare, SquarePen } from 'lucide-react-native';
import { useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';

import type { ChatTurn, Citation, Lang, Meeting, Speaker } from '@/api/types';
import { useKeyboardPadding } from '@/features/chat/keyboard';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { Banner, Button, Chip, EvidenceChip, styles as ui } from '@/ui/components';
import { IconTile } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { MarkdownLite } from '@/ui/markdown';
import { useTheme, type Theme } from '@/ui/theme';

import {
  CHAT_COUNTER_FROM,
  CHAT_MAX_CHARS,
  chatErrorText,
  chatMissingOnServer,
  chatModelLabel,
  chatRecordingGone,
  composerInset,
  newChatClientId,
} from './chatModel';
import { isChatSending, useChatHistory, useChatMutations, useChatOutgoing, useMeetingGone, type ChatOutgoing } from './queries';
import { renderTokens, speakerLabel } from './renderTokens';

/** Pastdan shuncha piksel ichida bo'lsa - "pastda" hisoblanadi (yangi xabarga ergashadi). */
const NEAR_BOTTOM = 80;

export interface ChatViewProps {
  meeting: Meeting;
  speakers: Speaker[];
  onSeek?: (t: number) => void;
  /** Tab maydoni ostidagi pleer balandligi: klaviatura ochilganda pleer uning ostida qoladi. */
  bottomInset?: number;
}

export function ChatView({ meeting, speakers, onSeek, bottomInset = 0 }: ChatViewProps) {
  const t = useT();
  const s = useChatStyles();
  const th = useTheme();
  const lang = useSettings((x) => x.uiLang);
  const insets = useSafeInsets();
  const kb = useKeyboardPadding(insets.bottom);
  const qc = useQueryClient();
  const ready = meeting.transcript.available;
  const history = useChatHistory(meeting.id, ready);
  const { send, reset } = useChatMutations(meeting.id);
  const outgoing = useChatOutgoing(meeting.id, history.data?.items);

  // Aylantirish (asosiy chat kabi): odam pastda turgan bo'lsa ro'yxat yangi xabarga ergashadi.
  const scroller = useRef<ScrollView>(null);
  const atBottom = useRef(true);
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    atBottom.current = contentSize.height - (contentOffset.y + layoutMeasurement.height) < NEAR_BOTTOM;
  };
  // Kontent o'sdi yoki ro'yxat qisqardi (klaviatura ochildi) - oxirgi xabar ko'rinib tursin.
  const follow = () => {
    if (atBottom.current) scroller.current?.scrollToEnd({ animated: false });
  };

  /**
   * true - yuborildi. Javob kutilayotganda (yoki bo'sh matn) - hech narsa qilinmaydi. `clientId` -
   * "Qayta yuborish"da o'sha xabarning kaliti (server takror savol-javob yaratmaydi); yangi xabar -
   * yangi kalit.
   */
  const submit = (text: string, clientId?: string): boolean => {
    const message = text.trim().slice(0, CHAT_MAX_CHARS);
    if (!message || isChatSending(qc, meeting.id)) return false;
    send.mutate({ message, language: lang, clientId: clientId || newChatClientId() });
    atBottom.current = true;
    requestAnimationFrame(() => scroller.current?.scrollToEnd({ animated: true }));
    return true;
  };

  const confirmReset = () =>
    Alert.alert(t('mchat.reset'), t('mchat.resetConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('mchat.resetOk'), style: 'destructive', onPress: () => reset.mutate() },
    ]);

  const items = history.data?.items ?? [];
  const pending = outgoing?.status === 'pending';
  // Tarix umuman kelmadi va 404 KODSIZ - serverda chat yo'q (eski backend): qayta urinish befoyda.
  // Boshqa xato - qayta urinish.
  const failed = history.isError && !history.data;
  const missing = failed && chatMissingOnServer(history.error);
  // `not_found` kodli 404 istalgan chat so'rovida - tarix (avval yuklangan bo'lsa ham), xabar yoki
  // "Yangi suhbat": yozuv o'chirilgan yoki begona. Ikkalasida chat yopiq - savol-javoblar, yozish
  // maydoni va "Qayta yuborish" ko'rsatilmaydi (xabar baribir o'sha 404 ni olardi).
  const gone =
    chatRecordingGone(history.error) ||
    chatRecordingGone(reset.error) ||
    (outgoing?.status === 'error' && chatRecordingGone(outgoing.error));
  const closed = missing || gone;
  useMeetingGone(meeting.id, gone);

  if (!ready) {
    return (
      <View style={s.pad}>
        <Banner tone="info" text={t('ask.notReady')} />
      </View>
    );
  }

  const model = chatModelLabel(history.data?.model);
  const quick = [
    { label: t('ask.quick.tasks'), q: t('ask.quick.tasksQ') },
    { label: t('ask.quick.decisions'), q: t('ask.quick.decisionsQ') },
    { label: t('ask.quick.followUp'), q: t('ask.quick.followUpQ') },
  ];

  return (
    <View
      style={[s.root, { paddingBottom: composerInset({ keyboard: kb.paddingBottom, navInset: insets.bottom, below: bottomInset }) }]}
      onLayout={kb.onLayout}>
      {items.length && !closed ? (
        <View style={s.head}>
          <Text style={s.headText} numberOfLines={1}>
            {model ? t('mchat.model', { model }) : ''}
          </Text>
          <Button
            testID="chat-reset"
            small
            variant="ghost"
            icon={SquarePen}
            title={t('mchat.reset')}
            onPress={confirmReset}
            disabled={pending || reset.isPending}
          />
        </View>
      ) : null}

      <ScrollView
        ref={scroller}
        testID="chat-scroll"
        style={s.list}
        contentContainerStyle={s.listContent}
        onScroll={onScroll}
        scrollEventThrottle={64}
        onContentSizeChange={follow}
        onLayout={follow}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="interactive">
        {history.isPending && !closed ? <ActivityIndicator style={s.spinner} color={th.textMuted} /> : null}
        {missing ? <Banner testID="chat-not-on-server" tone="info" text={t('mchat.notOnServer')} /> : null}
        {gone ? <Banner testID="chat-gone" tone="bad" text={t('recs.notFound')} /> : null}
        {failed && !closed ? (
          <Banner tone="bad" text={t('mchat.historyFailed')} action={{ title: t('common.retry'), onPress: () => void history.refetch() }} />
        ) : null}
        {history.data && !items.length && !outgoing && !closed ? (
          <View testID="chat-empty" style={s.empty}>
            <IconTile icon={MessagesSquare} tone="accent" size="lg" />
            <Text style={s.emptyText}>{t('mchat.empty')}</Text>
            <View style={[ui.wrap, s.center]}>
              {quick.map((c) => (
                <Chip key={c.label} label={c.label} tone="info" onPress={() => submit(c.q)} />
              ))}
            </View>
          </View>
        ) : null}
        {closed
          ? null
          : items.map((turn, i) => (
              <TurnView
                key={turn.id}
                turn={turn}
                speakers={speakers}
                lang={lang}
                onSeek={onSeek}
                // Takliflar faqat oxirgi javob ostida; javob kutilayotganda - yo'q (yuborib bo'lmaydi).
                followUps={i === items.length - 1 && !pending ? turn.followUps : []}
                onFollowUp={submit}
              />
            ))}
        {/* "Qayta yuborish" - O'SHA kalit bilan: server saqlagan bo'lsa takror yaratmaydi. */}
        {outgoing && !closed ? <OutgoingView outgoing={outgoing} onRetry={() => submit(outgoing.message, outgoing.clientId)} /> : null}
      </ScrollView>

      {closed ? null : <ChatComposer busy={pending} onSend={submit} />}
    </View>
  );
}

/** Bitta savol-javob: savol o'ngda, javob chapda, manbalar va (oxirgisida) keyingi savollar. */
function TurnView({
  turn,
  speakers,
  lang,
  onSeek,
  followUps,
  onFollowUp,
}: {
  turn: ChatTurn;
  speakers: Speaker[];
  lang: Lang;
  onSeek?: (t: number) => void;
  followUps: string[];
  onFollowUp: (q: string) => void;
}) {
  const s = useChatStyles();
  return (
    <View testID={`chat-turn-${turn.id}`} style={s.turn}>
      <Question text={turn.question} />
      <MarkdownLite text={renderTokens(turn.answer, speakers, lang)} />
      {turn.citations.map((c, i) => (
        <CitationRow key={`${c.segmentId}-${i}`} c={c} speakers={speakers} lang={lang} onSeek={onSeek} />
      ))}
      {followUps.length ? (
        <View style={[ui.wrap, s.followUps]}>
          {followUps.map((f, i) => (
            <Chip key={`${i}-${f}`} label={f} tone="accent" onPress={() => onFollowUp(f)} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** Manba: ▶ vaqt (pleer shu joydan) + kim aytgani va qisqa iqtibos. */
function CitationRow({ c, speakers, lang, onSeek }: { c: Citation; speakers: Speaker[]; lang: Lang; onSeek?: (t: number) => void }) {
  const s = useChatStyles();
  return (
    <View style={s.cite}>
      <EvidenceChip start={c.start} onSeek={onSeek} />
      <Text numberOfLines={1} style={s.citeText}>
        {c.speaker ? `${speakerLabel(c.speaker, speakers, lang)}: ` : ''}
        {c.text}
      </Text>
    </View>
  );
}

/** Hali tarixga kirmagan savol: javob kutilmoqda ("Barno yozmoqda…") yoki xato + "Qayta yuborish". */
function OutgoingView({ outgoing, onRetry }: { outgoing: ChatOutgoing; onRetry: () => void }) {
  const t = useT();
  const th = useTheme();
  const s = useChatStyles();
  return (
    <View style={s.turn}>
      <Question text={outgoing.message} testID="chat-outgoing" />
      {outgoing.status === 'pending' ? (
        <View testID="chat-typing" style={s.typing} accessibilityLiveRegion="polite">
          <ActivityIndicator size="small" color={th.brand} />
          <Text style={s.typingText}>{t('mchat.typing')}</Text>
        </View>
      ) : (
        <View testID="chat-error" style={s.errorBox} accessibilityRole="alert">
          <Text style={s.errorText}>{chatErrorText(t, outgoing.error)}</Text>
          <Pressable testID="chat-retry" onPress={onRetry} style={s.errorBtn} accessibilityRole="button" hitSlop={6}>
            <Text style={s.errorBtnText}>{t('mchat.resend')}</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

function Question({ text, testID }: { text: string; testID?: string }) {
  const s = useChatStyles();
  return (
    <View style={s.qRow}>
      <View testID={testID} style={s.bubble}>
        <Text style={s.qText} selectable>
          {text}
        </Text>
      </View>
    </View>
  );
}

/**
 * Yozish kartasi (asosiy chatdagi `Composer` ko'rinishida): ko'p qatorli matn + ↑ yuborish. Matn shu
 * yerda turadi - har harf butun suhbatni qayta chizmasin. Yuborish qabul qilinmasa (javob kutilmoqda)
 * matn o'chmaydi: javob kelgach yuboriladi.
 */
function ChatComposer({ onSend, busy }: { onSend: (text: string) => boolean; busy: boolean }) {
  const t = useT();
  const th = useTheme();
  const s = useChatStyles();
  const [value, setValue] = useState('');
  const canSend = !!value.trim() && !busy;
  return (
    <View style={s.composer}>
      <View style={s.card}>
        <TextInput
          testID="chat-input"
          value={value}
          onChangeText={setValue}
          multiline
          maxLength={CHAT_MAX_CHARS}
          placeholder={t('mchat.placeholder')}
          placeholderTextColor={th.textMuted}
          accessibilityLabel={t('mchat.placeholder')}
          style={s.input}
          textAlignVertical="top"
          autoCapitalize="sentences"
        />
        <Pressable
          testID="chat-send"
          accessibilityRole="button"
          accessibilityLabel={t('mchat.send')}
          accessibilityState={{ disabled: !canSend, busy }}
          disabled={!canSend}
          onPress={() => {
            if (onSend(value)) setValue('');
          }}
          hitSlop={5}
          style={({ pressed }) => [s.send, { opacity: canSend ? 1 : 0.45, transform: [{ scale: pressed ? 0.92 : 1 }] }]}>
          <ArrowUp size={19} color="#fff" strokeWidth={2.25} />
        </Pressable>
      </View>
      {value.length >= CHAT_COUNTER_FROM ? <Text style={s.counter}>{`${value.length}/${CHAT_MAX_CHARS}`}</Text> : null}
    </View>
  );
}

function useChatStyles() {
  const th = useTheme();
  return useMemo(() => makeStyles(th), [th]);
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    root: { flex: 1 },
    pad: { padding: 12 },
    head: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingTop: 8 },
    headText: { flex: 1, color: th.textMuted, fontSize: 12 },
    list: { flex: 1 },
    listContent: { flexGrow: 1, paddingHorizontal: 12, paddingTop: 4, paddingBottom: 12 },
    spinner: { marginTop: 32 },
    turn: { paddingTop: 14 },
    qRow: { flexDirection: 'row', justifyContent: 'flex-end', marginBottom: 10 },
    bubble: { maxWidth: '86%', backgroundColor: th.brandSoft, borderRadius: 20, borderBottomRightRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
    qText: { color: th.text, fontSize: 15, lineHeight: 22 },
    cite: { width: '100%', flexDirection: 'row', alignItems: 'center', marginTop: 2 },
    citeText: { flex: 1, color: th.textMuted, fontSize: 12, marginLeft: 4 },
    followUps: { marginTop: 8 },
    typing: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6 },
    typingText: { color: th.textMuted, fontSize: 15, flex: 1 },
    errorBox: { borderRadius: 14, backgroundColor: th.tones.bad.bg, padding: 12, gap: 10 },
    errorText: { color: th.tones.bad.fg, fontSize: 15, lineHeight: 21 },
    errorBtn: { alignSelf: 'flex-start', borderRadius: 999, backgroundColor: th.surface, paddingHorizontal: 14, paddingVertical: 8 },
    errorBtnText: { color: th.text, fontWeight: '600', fontSize: 14 },
    empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, paddingVertical: 24, paddingHorizontal: 8 },
    emptyText: { color: th.textMuted, fontSize: 15, lineHeight: 22, textAlign: 'center' },
    center: { justifyContent: 'center' },
    composer: { paddingHorizontal: 12, paddingTop: 6, paddingBottom: 8 },
    card: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      gap: 8,
      borderWidth: 1,
      borderColor: th.composerLine,
      borderRadius: 24,
      backgroundColor: th.composerBg,
      paddingLeft: 16,
      paddingRight: 6,
      paddingVertical: 6,
      ...(th.dark
        ? null
        : { shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 2 }),
    },
    input: { flex: 1, color: th.text, fontSize: 16, lineHeight: 22, maxHeight: 132, paddingTop: 7, paddingBottom: 7, paddingHorizontal: 0 },
    send: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: th.brand },
    counter: { color: th.textMuted, fontSize: 11, textAlign: 'right', marginTop: 4, marginRight: 10 },
  });
}
