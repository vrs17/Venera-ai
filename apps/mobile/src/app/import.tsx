/**
 * "Ulashish -> Barno AI" tasdiq ekrani: ulashilgan audio fayl(lar), suhbat tili va
 * "Yuborish" / "Bekor qilish".
 *
 * NIMA UCHUN doim tasdiq: deep link'ni istalgan ilova ochishi mumkin. Fayl foydalanuvchi
 * bilmasdan serverga ketmasligi kerak - shuning uchun avtomatik yuborish yo'q (o'rnatish
 * kaliti ham import havolasida ishlatilmaydi).
 *
 * Yuborilganda fayl `imports/` dan `recordings/` ga ko'chadi va oddiy navbat qatori bo'ladi
 * (source `share`): yuklash, oflayn kutish va xulosa yozuvlar bilan bir xil.
 */
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { AudioLines, FileXCorner, Phone, Send } from 'lucide-react-native';
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Lang } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { currentSendOptions } from '@/features/calls/CallAutoSend';
import { limitMb, toastSendOutcome } from '@/features/calls/feedback';
import { useCalls } from '@/features/calls/callsStore';
import { displayStartMs, formatSize, parseCallFileName } from '@/features/calls/fileName';
import { discardImports, importItemStatus, importSendDeps, loadImportItems, type ImportItem, type ImportItemStatus } from '@/features/calls/importFiles';
import { confirmCallConsent } from '@/features/calls/permission';
import { sendImportedFile, type SendOutcome } from '@/features/calls/send';
import { parseImportParams } from '@/features/entry/deepLink';
import { formatDateTime, formatDuration } from '@/features/meeting/formatDate';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { useServices } from '@/services';
import { Banner, Button, Chip } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { showToast } from '@/ui/errors';
import { IconTile } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup } from '@/ui/list';
import { StatusPill } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

const LANGS: Lang[] = ['uz', 'ru', 'en'];

type Raw = { files?: string | string[]; skipped?: string | string[]; n?: string | string[] };

const joinParam = (v: string | string[] | undefined): string => (Array.isArray(v) ? v.join(',') : (v ?? ''));

function statusLabel(t: TFn, st: ImportItemStatus, maxBytes: number | null): string | null {
  if (st === 'missing') return t('calls.import.missing');
  if (st === 'unsupported') return t('calls.unsupported');
  if (st === 'too_large') return t('calls.tooLarge', { mb: maxBytes ? limitMb(maxBytes) : '' });
  return null;
}

/**
 * Yuboriladigan fayl yo'q - SABABI (spec: haqiqiy sabab): hammasi katta / hammasi formati mos
 * emas / hammasi yo'q. Aralash bo'lsa umumiy matn yo'q - har kartadagi pill sababni aytadi.
 */
function emptyBody(t: TFn, statuses: ImportItemStatus[], skipped: number, maxBytes: number | null): string | null {
  if (!statuses.length) return skipped > 0 ? t('calls.import.skipped', { n: skipped }) : t('calls.import.emptyBody');
  if (statuses.every((st) => st === 'too_large')) return t('calls.import.tooLargeBody', { mb: maxBytes ? limitMb(maxBytes) : '' });
  if (statuses.every((st) => st === 'unsupported')) return t('calls.import.unsupportedBody');
  if (statuses.every((st) => st === 'missing')) return t('calls.import.emptyBody');
  return null;
}

export default function ImportScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const uiLang = useSettings((s) => s.uiLang);
  const services = useServices();
  const maxBytes = useAuth((s) => s.config?.maxUploadBytes || null);
  const raw = useLocalSearchParams<Raw>();
  const filesKey = joinParam(raw.files);
  const skippedRaw = joinParam(raw.skipped);
  const nonce = joinParam(raw.n);
  const params = useMemo(() => parseImportParams({ files: filesKey, skipped: skippedRaw, n: nonce }), [filesKey, skippedRaw, nonce]);
  // Qaysi ulashish uchun o'qilgan: yangi `n`/fayllar kelganda eski ro'yxat bir lahza ham ko'rinmasin.
  const loadKey = `${params.files.join(',')}|${params.n ?? ''}`;
  const [loaded, setLoaded] = useState<{ key: string; items: ImportItem[] } | null>(null);
  const items = loaded?.key === loadKey ? loaded.items : null;
  const [language, setLanguage] = useState<Lang>(() => useCalls.getState().language ?? useSettings.getState().lastLanguage);
  const [sending, setSending] = useState(false);
  const consentSeen = useCalls((s) => s.consentAt != null);

  // Har yangi ulashish (yangi `n`) - fayllar qaytadan o'qiladi.
  useEffect(() => {
    let alive = true;
    loadImportItems(params.files)
      .then((list) => alive && setLoaded({ key: loadKey, items: list }))
      .catch(() => alive && setLoaded({ key: loadKey, items: [] }));
    return () => {
      alive = false;
    };
  }, [params, loadKey]);

  const statuses = useMemo(() => (items ?? []).map((it) => importItemStatus(it, maxBytes)), [items, maxBytes]);
  const sendable = (items ?? []).flatMap((it, i) => (statuses[i] === 'ok' && it.meta ? [it.meta] : []));

  const leave = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/');
  };

  const cancel = () => {
    discardImports(params.files);
    leave();
  };

  const send = async () => {
    if (!sendable.length || sending) return;
    if (!(await confirmCallConsent(t))) return;
    setSending(true);
    const opts = { ...currentSendOptions(t), language };
    const deps = importSendDeps(services);
    let queued = 0;
    let problem: SendOutcome | null = null;
    try {
      for (const meta of sendable) {
        const out = await sendImportedFile(deps, meta, opts);
        if (out.kind === 'queued') queued++;
        else problem = out;
      }
    } finally {
      setSending(false);
    }
    void services.uploader.runOnce().catch(() => {});
    // Yuborilmagan (format, hajm, xato) fayllar imports/ da qolib ketmasin - kerak bo'lsa qayta ulashadi.
    discardImports(params.files);
    // Bittasi bo'lsa ham ketdi - "yuborilmadi" deb qo'rqitmaymiz; hech biri ketmasa - sababi.
    if (queued) showToast(queued === 1 ? t('calls.import.queuedOne') : t('calls.import.queued', { n: queued }));
    else if (problem) toastSendOutcome(t, problem);
    if (queued) router.replace('/meetings');
    else leave();
  };

  return (
    <View style={[s.root, { backgroundColor: th.bg }]}>
      <Stack.Screen options={{ title: t('calls.import.title') }} />
      {items === null ? (
        <View style={s.loading}>
          <ActivityIndicator color={th.textMuted} />
        </View>
      ) : items.length === 0 || !sendable.length ? (
        <View style={s.root}>
          {items.length > 0 ? (
            <View style={s.emptyList}>
              <ImportList items={items} statuses={statuses} lang={uiLang} maxBytes={maxBytes} />
            </View>
          ) : null}
          <EmptyState
            testID="import-empty"
            icon={FileXCorner}
            tone="warn"
            // Ro'yxat ustida bo'lsa ixcham: ekranda ikkita "markaz" bo'lmasin.
            compact={items.length > 0}
            title={t('calls.import.emptyTitle')}
            body={emptyBody(t, statuses, params.skipped, maxBytes)}
            action={{
              title: t('calls.import.toRecordings'),
              variant: 'secondary',
              testID: 'import-to-recordings',
              onPress: () => {
                discardImports(params.files);
                router.replace('/meetings');
              },
            }}
          />
        </View>
      ) : (
        <ScrollView contentContainerStyle={[s.content, { paddingBottom: 32 + insets.bottom }]} testID="import-screen">
          {params.skipped > 0 ? <Banner tone="warn" testID="import-skipped" text={t('calls.import.skipped', { n: params.skipped })} /> : null}
          <ImportList items={items} statuses={statuses} lang={uiLang} maxBytes={maxBytes} />
          <ListGroup header={t('calls.language')}>
            <View style={s.chips} testID="import-language">
              {LANGS.map((l) => (
                <Chip
                  key={l}
                  testID={`import-lang-${l}`}
                  label={t(`lang.${l}`)}
                  tone={language === l ? 'accent' : 'neutral'}
                  selected={language === l}
                  onPress={() => setLanguage(l)}
                />
              ))}
            </View>
          </ListGroup>
          {/* Eslatma faqat qo'ng'iroq yozuvi bo'lsa va rozilik oynasi allaqachon ko'rilgan bo'lsa - aks holda "Yuborish" o'zi so'raydi (ikki marta aytilmasin). */}
          {consentSeen && items.some((it) => parseCallFileName(it.meta?.displayName ?? it.name).looksLikeCall) ? (
            <Text style={[typeScale.caption, s.note, { color: th.textMuted }]}>{t('calls.import.note')}</Text>
          ) : null}
          <View style={s.actions}>
            <Button
              testID="import-send"
              icon={Send}
              pill
              title={sendable.length === 1 ? t('calls.send') : t('calls.import.send', { n: sendable.length })}
              loading={sending}
              onPress={() => void send()}
            />
            <Button testID="import-cancel" variant="ghost" pill title={t('common.cancel')} disabled={sending} onPress={cancel} />
          </View>
        </ScrollView>
      )}
    </View>
  );
}

function ImportList({ items, statuses, lang, maxBytes }: { items: ImportItem[]; statuses: ImportItemStatus[]; lang: Lang; maxBytes: number | null }) {
  const t = useT();
  const th = useTheme();
  return (
    <View style={s.list}>
      {items.map((it, i) => {
        const meta = it.meta;
        const parsed = parseCallFileName(meta?.displayName ?? it.name);
        const title = parsed.counterpart ?? meta?.displayName ?? it.name;
        const parts: string[] = [];
        if (meta) {
          const start = displayStartMs(parsed, meta.dateMs, meta.durationMs);
          if (start != null) parts.push(formatDateTime(start, lang));
          if (meta.durationMs > 0) parts.push(formatDuration(meta.durationMs / 1000));
          parts.push(formatSize(meta.sizeBytes, t, lang));
        }
        const label = statusLabel(t, statuses[i], maxBytes);
        return (
          <View key={it.name} testID={`import-item-${it.name}`} style={[s.card, { backgroundColor: th.surfaceAlt }]}>
            <IconTile icon={parsed.looksLikeCall ? Phone : AudioLines} tone="raised" />
            <View style={s.body}>
              <Text numberOfLines={2} style={[typeScale.rowTitle, { color: th.text }]}>
                {title}
              </Text>
              {parts.length ? (
                <Text numberOfLines={1} style={[typeScale.caption, s.meta, { color: th.textMuted }]}>
                  {parts.filter(Boolean).join(' · ')}
                </Text>
              ) : null}
            </View>
            {label ? <StatusPill label={label} tone="warn" /> : null}
          </View>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  loading: { paddingVertical: 48, alignItems: 'center' },
  content: { padding: 16, gap: 16 },
  list: { gap: 8 },
  emptyList: { paddingHorizontal: 16, paddingTop: 16 },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: radius.lg, padding: 14 },
  body: { flex: 1, minWidth: 0 },
  meta: { marginTop: 2, fontVariant: ['tabular-nums'] },
  chips: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 4 },
  note: { paddingHorizontal: 4 },
  actions: { gap: 8 },
});
