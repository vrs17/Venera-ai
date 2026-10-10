/**
 * Ulashish va eksport varag'i (Plaud'dagidek): format (PDF, Word, Markdown, matn, audio
 * fayl) va hujjat qismlari (Qisqa xulosa, Xulosa, Vazifalar, Aqliy xarita, Transkript),
 * pastda bitta "Ulashish" tugmasi.
 *
 * Oqim: fayl serverda chiziladi (`GET /meetings/{id}/export`, audio - `/audio?download=1`),
 * `Authorization` bilan telefon keshiga yuklanadi va Android ulashish oynasi ochiladi
 * (Telegram, Gmail, Drive...). Hujjat har doim "Qisqa xulosa" bilan boshlanadi - buni
 * server tartibi ta'minlaydi (`MEETING_EXPORT_PARTS`).
 *
 * Xatolar SABABi bilan (spec "Honest"): internet yo'q, oldingi fayl hali tayyorlanmoqda
 * (429/503 `export_busy`), soatlik chegara (429 `rate_limited`), xulosa tayyor emas
 * (409 `not_ready` -> "Faqat transkript"), serverda PDF/Word chizib bo'lmaydi (503
 * `pdf_unavailable` -> "Word'da ulashish"), yuklash uzilib qoldi (`stalled` -> qayta urinish),
 * audio muddati o'tgan (410 - qayta urinish TAKLIF QILINMAYDI: baribir bo'lmaydi).
 *
 * Standart tarkib: Qisqa xulosa + To'liq xulosa + Vazifalar. Aqliy xarita va transkript - odam
 * o'zi yoqsa (bir soatlik yig'ilish transkripti 20+ sahifa; rahbarga odatda xulosa yuboriladi).
 * Oxirgi tanlov ilova ochiq turganda eslab qolinadi.
 */
import {
  AudioLines,
  FileCode,
  FileText,
  FileType,
  ListChecks,
  Network,
  NotebookText,
  ScrollText,
  Share2,
  Sparkles,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react-native';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import {
  downloadWithAuth,
  fileNameFromDisposition,
  headerOf,
  MEETING_EXPORT_PARTS,
  SHARE_FILE_TYPES,
  SUMMARY_EXPORT_PARTS,
  type FileDownloader,
  type MeetingExportFormat,
  type MeetingExportPart,
} from '@/api/meetings';
import type { TFn, TKey } from '@/i18n';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useOnline } from '@/features/upload/uploadStatus';
import { useServices } from '@/services';
import { Banner, Button } from '@/ui/components';
import { errorText } from '@/ui/errors';
import { IconTile, type IconTileTone } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme, type Theme } from '@/ui/theme';
import { iconSize, stroke, type as typeScale } from '@/ui/tokens';

export type ShareChoice = MeetingExportFormat | 'audio';

export interface ExportSheetProps {
  visible: boolean;
  onClose: () => void;
  meetingId: string;
  title: string;
  /** Eksport qilinadigan xulosa TAYYOR - aks holda faqat transkript (xulosa qismlari o'chiq). */
  hasSummary: boolean;
  /**
   * Xulosa tabida ko'rib turilgan xulosa (boshqa shablon). Yo'q - asosiy xulosa: odam qaysi
   * "Qisqa xulosa"ni o'qib turgan bo'lsa, faylda ham o'sha bo'lsin.
   */
  summaryId?: string | null;
}

const FORMATS: { value: ShareChoice; title: TKey; hint: TKey; icon: LucideIcon; tone: IconTileTone }[] = [
  { value: 'pdf', title: 'share.fmt.pdf', hint: 'share.fmt.pdfHint', icon: FileText, tone: 'bad' },
  { value: 'docx', title: 'share.fmt.docx', hint: 'share.fmt.docxHint', icon: FileType, tone: 'info' },
  { value: 'md', title: 'share.fmt.md', hint: 'share.fmt.mdHint', icon: FileCode, tone: 'raised' },
  { value: 'txt', title: 'share.fmt.txt', hint: 'share.fmt.txtHint', icon: NotebookText, tone: 'raised' },
  { value: 'audio', title: 'share.fmt.audio', hint: 'share.fmt.audioHint', icon: AudioLines, tone: 'accent' },
];

const PART_ROWS: Record<MeetingExportPart, { title: TKey; icon: LucideIcon }> = {
  brief: { title: 'share.part.brief', icon: Zap },
  summary: { title: 'share.part.summary', icon: Sparkles },
  actions: { title: 'share.part.actions', icon: ListChecks },
  mindmap: { title: 'share.part.mindmap', icon: Network },
  transcript: { title: 'share.part.transcript', icon: ScrollText },
};

/** Xulosa tayyor bo'lmasa ham beriladigan yagona qism. */
const TRANSCRIPT_ONLY: MeetingExportPart[] = ['transcript'];
/** Standart tarkib - rahbar/hamkasbga yuboriladigan qism; xarita va transkript - qo'shimcha. */
export const DEFAULT_EXPORT_PARTS: readonly MeetingExportPart[] = ['brief', 'summary', 'actions'];

// Oxirgi tanlangan format va tarkib - shu ilova ochiq turganda eslab qolinadi (kim PDF yuborsa,
// keyingi safar ham PDF). Sozlamaga yozilmaydi: bu qulaylik, holat emas.
let lastChoice: ShareChoice = 'pdf';
let lastParts: MeetingExportPart[] | null = null;

export function defaultParts(hasSummary: boolean, remembered: readonly MeetingExportPart[] | null = lastParts): MeetingExportPart[] {
  if (!hasSummary) return [...TRANSCRIPT_ONLY];
  return [...(remembered?.length ? remembered : DEFAULT_EXPORT_PARTS)];
}

/** Testlar uchun: modul darajasidagi eslab qolingan tanlovni tozalash. */
export function resetExportMemory(): void {
  lastChoice = 'pdf';
  lastParts = null;
}

// --- Xatoni sababga aylantirish -------------------------------------------------------------------

export type ShareProblem =
  | { kind: 'offline' }
  | { kind: 'stalled' }
  | { kind: 'audioExpired' }
  /** Qayta urinish yordam bermaydi (403/404/410...): faqat sababi. */
  | { kind: 'final'; err: unknown }
  | { kind: 'busy'; server: boolean }
  | { kind: 'rateLimited' }
  | { kind: 'notReady'; audio: boolean; nothing: boolean; transcriptOnly: boolean }
  | { kind: 'pdfUnavailable' }
  | { kind: 'docxUnavailable' }
  | { kind: 'cannotShare' }
  | { kind: 'error'; err: unknown };

/** Server javobi (`ApiError.code`, 409 dagi `available`) -> ekranda nima deyish va nima taklif qilish. */
export function shareProblem(err: unknown, choice: ShareChoice, parts: readonly MeetingExportPart[]): ShareProblem {
  if (!(err instanceof ApiError)) return { kind: 'error', err };
  if (err.status === 0 && err.code === 'network') return { kind: 'offline' };
  if (err.status === 0 && err.code === 'stalled') return { kind: 'stalled' };
  if (err.status === 410) return choice === 'audio' ? { kind: 'audioExpired' } : { kind: 'final', err };
  if (err.status === 403 || err.status === 404) return { kind: 'final', err };
  if (err.code === 'export_busy') return { kind: 'busy', server: err.status !== 429 };
  if (err.status === 429) return { kind: 'rateLimited' };
  if (err.code === 'pdf_unavailable') return { kind: 'pdfUnavailable' };
  if (err.code === 'docx_unavailable') return { kind: 'docxUnavailable' };
  if (err.status === 409) {
    if (choice === 'audio') return { kind: 'notReady', audio: true, nothing: false, transcriptOnly: false };
    const raw = err.body?.available;
    const available = Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : [];
    const wantsSummary = parts.some((p) => SUMMARY_EXPORT_PARTS.includes(p));
    return {
      kind: 'notReady',
      audio: false,
      nothing: available.length === 0,
      // Transkript tayyor, xulosa yo'q - shu zahoti "faqat transkript" bilan qayta so'rash mumkin.
      transcriptOnly: wantsSummary && available.includes('transcript'),
    };
  }
  return { kind: 'error', err };
}

function problemText(t: TFn, p: ShareProblem): string {
  switch (p.kind) {
    case 'offline':
      return t('share.offline');
    case 'stalled':
      return t('share.stalled');
    case 'audioExpired':
      return t('share.audioExpired');
    case 'busy':
      return p.server ? t('share.serverBusy') : t('share.busy');
    case 'rateLimited':
      return t('share.rateLimited');
    case 'notReady':
      return p.audio ? t('share.audioNotReady') : p.nothing ? t('share.notReadyAll') : t('share.notReady');
    case 'pdfUnavailable':
      return t('share.pdfUnavailable');
    case 'docxUnavailable':
      return t('share.docxUnavailable');
    case 'cannotShare':
      return t('share.unavailable');
    default:
      return errorText(t, p.err);
  }
}

// --- Native qatlam (faqat "Ulashish" bosilganda yuklanadi) ------------------------------------------

interface ShareNative {
  io: FileDownloader;
  /** Eksport papkasi `.../cache/exports/` (chiqishda va ilova ochilganda ham tozalanadi - `lib/paths`). */
  /** Eksport papkasi (`.../cache/exports/`), oldingi fayllardan tozalangan. */
  freshDir(): Promise<string>;
  move(from: string, to: string): Promise<void>;
  canShare(): Promise<boolean>;
  share(uri: string, mimeType: string, dialogTitle: string): Promise<void>;
}

/**
 * NIMA UCHUN `expo-file-system/legacy` ning `createDownloadResumable`i: u xato statusda ham
 * tanani faylga yozib `status` qaytaradi - 409/503 dagi server kodi (`pdf_unavailable`,
 * `export_busy`, `available`) o'qiladi. Yangi `File.downloadFileAsync` esa faqat
 * "HTTP 503" deydi - PDF yo'qmi yoki server bandmi, ajratib bo'lmasdi. Oddiy `downloadAsync`
 * emas: u oqim o'rtasida uzilsa va'dani hech qachon tugatmasdi; resumable - xatoda reject
 * qiladi, bekor qilinadi (`cancelAsync`) va progress beradi (qo'riqchi shunga tayanadi).
 * `require` - native modullar faqat ulashish paytida yuklanadi (ekran va testlar ularsiz).
 */
function nativeShare(): ShareNative {
  /* eslint-disable @typescript-eslint/no-require-imports */
  const FS = require('expo-file-system/legacy') as typeof import('expo-file-system/legacy');
  const Sharing = require('expo-sharing') as typeof import('expo-sharing');
  /* eslint-enable @typescript-eslint/no-require-imports */
  return {
    io: {
      async download(url, fileUri, headers, control) {
        const task = FS.createDownloadResumable(url, fileUri, { headers }, (p) =>
          control?.onProgress?.({ written: p.totalBytesWritten, total: p.totalBytesExpectedToWrite }),
        );
        const cancel = () => void task.cancelAsync().catch(() => {});
        control?.signal?.addEventListener('abort', cancel);
        try {
          const r = await task.downloadAsync();
          if (!r) throw new Error('cancelled');
          return { status: r.status, uri: r.uri, headers: r.headers ?? {} };
        } finally {
          control?.signal?.removeEventListener('abort', cancel);
        }
      },
      readText: (uri) => FS.readAsStringAsync(uri),
      remove: (uri) => FS.deleteAsync(uri, { idempotent: true }),
    },
    async freshDir() {
      const dir = `${FS.cacheDirectory ?? ''}exports/`;
      // Oldingi eksport (audio o'nlab MB bo'lishi mumkin) keshda yig'ilib qolmasin. Ulashishdan
      // DARHOL keyin emas, keyingi eksportda tozalanadi: qabul qilgan ilova (Telegram) faylni
      // ulashish oynasi yopilgandan keyin ham o'qib turgan bo'lishi mumkin.
      await FS.deleteAsync(dir, { idempotent: true });
      await FS.makeDirectoryAsync(dir, { intermediates: true });
      return dir;
    },
    move: (from, to) => FS.moveAsync({ from, to }),
    canShare: () => Sharing.isAvailableAsync(),
    share: (uri, mimeType, dialogTitle) => Sharing.shareAsync(uri, { mimeType, dialogTitle }),
  };
}

// --- Varaq ----------------------------------------------------------------------------------------

function rememberChoice(c: ShareChoice): void {
  lastChoice = c;
}

/** Faylga yuklash uchun vaqtinchalik nom (har urinish o'zinikini oladi). */
function partFileName(): string {
  return `download-${Date.now()}.part`;
}

export function ExportSheet(props: ExportSheetProps) {
  // Ichki qism faqat ochiq paytda mount bo'ladi: har ochilishda toza holat (format - oxirgi
  // tanlov, qismlar - hozirgi `hasSummary`dan; xulosa endi tayyor bo'lgan bo'lishi mumkin).
  // Yopilganda yarim qolgan yuklash natijasi ham shu bilan "eskiradi".
  return (
    <Modal visible={props.visible} transparent animationType="slide" onRequestClose={props.onClose} statusBarTranslucent>
      {props.visible ? <ExportBody {...props} /> : null}
    </Modal>
  );
}

function ExportBody({ onClose, meetingId, title, hasSummary, summaryId }: ExportSheetProps) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const insets = useSafeInsets();
  const { meetings, session } = useServices();
  const uiLang = useSettings((x) => x.uiLang);
  const online = useOnline();

  const [choice, setChoice] = useState<ShareChoice>(lastChoice);
  const [parts, setParts] = useState<MeetingExportPart[]>(() => defaultParts(hasSummary));
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [problem, setProblem] = useState<ShareProblem | null>(null);
  // Har ulashish urinishining raqami: varaq yopilsa yoki qayta bosilsa eski natija
  // (kech kelgan fayl) ulashish oynasini ochmaydi va xatoni ko'rsatmaydi.
  const run = useRef(0);
  const alive = useRef(true);
  // Joriy yuklash: varaq yopilsa (yoki yangisi boshlansa) native yuklash ham to'xtaydi -
  // o'nlab MB audio fonda yuklanib, keshni to'ldirib yotmasin.
  const download = useRef<AbortController | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      download.current?.abort();
    };
  }, []);

  const isDoc = choice !== 'audio';
  // Xulosa yo'q bo'lsa xulosa qismlari yuborilmaydi (server 409 berardi).
  const sendParts = hasSummary ? parts : parts.filter((p) => !SUMMARY_EXPORT_PARTS.includes(p));
  const canSend = !busy && (!isDoc || sendParts.length > 0);

  const pick = (c: ShareChoice) => {
    rememberChoice(c);
    setChoice(c);
    setProblem(null);
  };

  const toggle = (p: MeetingExportPart) => {
    setProblem(null);
    setParts((prev) => {
      const next = prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p];
      // Faqat odamning o'z tanlovi eslab qolinadi (xulosasiz yozuvdagi "faqat transkript" emas).
      if (hasSummary) lastParts = next;
      return next;
    });
  };

  const share = async (c: ShareChoice, list: readonly MeetingExportPart[]) => {
    const mine = ++run.current;
    const current = () => alive.current && mine === run.current;
    download.current?.abort();
    const ctl = new AbortController();
    download.current = ctl;
    setBusy(true);
    setProgress(null);
    setProblem(null);
    try {
      const nat = nativeShare();
      if (!(await nat.canShare())) {
        if (current()) setProblem({ kind: 'cannotShare' });
        return;
      }
      const url = c === 'audio' ? meetings.audioDownloadUrl(meetingId) : meetings.exportUrl(meetingId, { format: c, parts: list, summaryId });
      const dir = await nat.freshDir();
      const res = await downloadWithAuth(url, `${dir}${partFileName()}`, {
        tokens: session,
        io: nat.io,
        language: uiLang,
        signal: ctl.signal,
        // Foiz faqat hajm ma'lum bo'lsa (audio); hujjat odatda bir zumda keladi.
        onProgress: (p) => {
          if (current() && p.total > 0) setProgress(Math.min(100, Math.round((p.written / p.total) * 100)));
        },
      });
      const type = SHARE_FILE_TYPES[c];
      const contentType = (headerOf(res.headers, 'Content-Type') ?? '').split(';')[0].trim();
      // Audio serverda m4a yoki (qayta o'rash bo'lmasa) asl AAC - nom va MIME javobdan.
      const ext = c === 'audio' && contentType === 'audio/aac' ? 'aac' : type.ext;
      const mime = c === 'audio' && contentType.startsWith('audio/') ? contentType : type.mime;
      const name = fileNameFromDisposition(headerOf(res.headers, 'Content-Disposition'), title, ext);
      // URI ichida nom kodlanadi: "#" yoki "%" bo'lsa ham `Uri.parse` yo'lni buzmasin.
      const target = `${dir}${encodeURIComponent(name)}`;
      await nat.move(res.uri, target);
      if (!current()) return;
      await nat.share(target, mime, title || name);
      if (current()) onClose();
    } catch (e) {
      if (current()) setProblem(shareProblem(e, c, list));
    } finally {
      if (download.current === ctl) download.current = null;
      if (current()) {
        setBusy(false);
        setProgress(null);
      }
    }
  };

  const next = problemAction(problem);
  const runNext = (kind: NextStep) => {
    if (kind === 'transcriptOnly') {
      setParts([...TRANSCRIPT_ONLY]);
      void share(choice, TRANSCRIPT_ONLY);
    } else if (kind === 'retry') {
      void share(choice, sendParts);
    } else {
      pick(kind);
      void share(kind, sendParts);
    }
  };

  return (
    <View style={s.backdrop}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel={t('common.close')} />
      <View style={[s.sheet, { paddingBottom: Math.max(insets.bottom, 12) }]} testID="export-sheet">
        <View style={s.grabber} />
        <View style={s.head}>
          <View style={s.headText}>
            <Text style={[typeScale.headline, { color: th.text }]} accessibilityRole="header">
              {t('share.title')}
            </Text>
            {title ? (
              <Text style={[typeScale.caption, { color: th.textMuted }]} numberOfLines={1}>
                {title}
              </Text>
            ) : null}
          </View>
          <Pressable
            testID="export-close"
            onPress={onClose}
            hitSlop={10}
            accessibilityRole="button"
            accessibilityLabel={t('common.close')}
            style={s.close}>
            <X size={iconSize.sm} color={th.textSoft} strokeWidth={stroke.small} />
          </Pressable>
        </View>

        <ScrollView style={s.scroll} contentContainerStyle={s.scrollBody} keyboardShouldPersistTaps="handled">
          <ListGroup header={t('share.formats')}>
            {FORMATS.map((f) => (
              <ListRow
                key={f.value}
                testID={`export-fmt-${f.value}`}
                title={t(f.title)}
                subtitle={t(f.hint)}
                leading={<IconTile icon={f.icon} tone={f.tone} size="sm" />}
                right={{ kind: 'check', checked: choice === f.value }}
                onPress={() => pick(f.value)}
                disabled={busy}
              />
            ))}
          </ListGroup>

          {isDoc ? (
            <ListGroup header={t('share.parts')} footer={hasSummary ? undefined : t('share.noSummary')}>
              {MEETING_EXPORT_PARTS.map((p) => {
                const needsSummary = SUMMARY_EXPORT_PARTS.includes(p);
                const off = needsSummary && !hasSummary;
                return (
                  <ListRow
                    key={p}
                    testID={`export-part-${p}`}
                    title={t(PART_ROWS[p].title)}
                    icon={PART_ROWS[p].icon}
                    disabled={off || busy}
                    right={{
                      kind: 'switch',
                      value: !off && parts.includes(p),
                      onChange: () => toggle(p),
                      disabled: off || busy,
                      testID: `export-part-${p}-switch`,
                    }}
                  />
                );
              })}
            </ListGroup>
          ) : null}

          {problem ? (
            <Banner
              testID="export-problem"
              tone={problem.kind === 'error' || problem.kind === 'final' ? 'bad' : 'warn'}
              text={problemText(t, problem)}
              action={next ? { title: t(next.title), onPress: () => runNext(next.kind) } : undefined}
            />
          ) : online === false ? (
            <Banner testID="export-offline" tone="warn" text={t('share.offline')} />
          ) : null}
        </ScrollView>

        <View style={s.footer}>
          {busy ? (
            <View style={s.status} accessibilityLiveRegion="polite">
              <ActivityIndicator size="small" color={th.textMuted} />
              <Text style={[typeScale.caption, { color: th.textMuted }]} testID="export-status">
                {progress != null ? t('share.progress', { pct: progress }) : t('share.preparing')}
              </Text>
            </View>
          ) : isDoc && sendParts.length === 0 ? (
            <Text style={[typeScale.caption, s.hint, { color: th.textMuted }]}>{t('share.pickPart')}</Text>
          ) : null}
          <Button
            testID="export-share"
            title={t('share.send')}
            icon={Share2}
            pill
            loading={busy}
            disabled={!canSend}
            onPress={() => void share(choice, sendParts)}
          />
        </View>
      </View>
    </View>
  );
}

type NextStep = 'retry' | 'transcriptOnly' | MeetingExportFormat;

/** Xatodan keyin taklif qilinadigan BITTA keyingi qadam (yoki yo'q). */
function problemAction(p: ShareProblem | null): { title: TKey; kind: NextStep } | null {
  if (!p) return null;
  switch (p.kind) {
    case 'offline':
    case 'stalled':
    case 'busy':
    case 'error':
      return { title: 'common.retry', kind: 'retry' };
    case 'notReady':
      return p.transcriptOnly ? { title: 'share.transcriptOnly', kind: 'transcriptOnly' } : null;
    case 'pdfUnavailable':
      return { title: 'share.useDocx', kind: 'docx' };
    case 'docxUnavailable':
      return { title: 'share.usePdf', kind: 'pdf' };
    default:
      return null;
  }
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.45)' },
    sheet: { backgroundColor: th.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: '90%', paddingTop: 8 },
    grabber: { alignSelf: 'center', width: 36, height: 4, borderRadius: 2, backgroundColor: th.borderStrong, marginBottom: 6 },
    head: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingTop: 4, paddingBottom: 12 },
    headText: { flex: 1, minWidth: 0, gap: 2 },
    close: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: th.surfaceAlt },
    scroll: { flexGrow: 0, flexShrink: 1 },
    scrollBody: { paddingHorizontal: 16 },
    footer: { paddingHorizontal: 16, paddingTop: 8, gap: 8 },
    status: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
    hint: { textAlign: 'center' },
  });
}
