/**
 * Bayonnoma varag'i - yig'ilish yozuvidan RASMIY hujjat loyihasi (kun tartibi, bayon,
 * raqamlangan qaror bandlari). Slack va Telegram'dagi «📄 Bayonnoma» bilan bir xil server oqimi.
 *
 * Tanlov: hujjat tili (o'zbekcha kirill/lotin, rus, ingliz - default yig'ilish tilidan, server
 * qoidasi: uz -> kirill) va format (Word - asosiy, kotib shu faylda to'ldiradi; PDF - nusxa).
 * Til kodi DOIM aniq yuboriladi: serverda `uz` lotin, bo'sh - kirill degani.
 *
 * Oqim: ochilganda `GET /minutes` - tanlangan tilda tayyor va eskirmagan hujjat bo'lsa darhol
 * "Ulashish" (+ "Qayta yozish" = `force`). Bo'lmasa "Tayyorlash" -> `POST /minutes`. Javob
 * `running` (202 yoki 200 - allaqachon yozilayotgan) bo'lsa har 3 s da `GET /minutes/{id}` -
 * tayyor/xato bo'lguncha; 10 daqiqadan keyin so'rash to'xtaydi va halol aytiladi ("odatdagidan
 * uzoq - keyinroq qarang"). Varaq yopilsa server ishi BEKOR QILINMAYDI: qayta ochilganda
 * ro'yxatdan davom etadi.
 *
 * Ulashish ExportSheet bilan bir yo'l (`shareFile.ts`): `.../minutes/{id}/export?format=` fayli
 * `Authorization` bilan keshga, so'ng Android ulashish oynasi. Hujjat LOYIHA ekani doim aytiladi:
 * «________» joylarini kotib yoki hujjat tizimi to'ldiradi.
 */
import { FileCheck, FilePen, FileText, FileType, RotateCcw, Share2, X, type LucideIcon } from 'lucide-react-native';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { fileNameFromDisposition, headerOf, SHARE_FILE_TYPES } from '@/api/meetings';
import type { Lang, MinutesLanguage, MinutesView } from '@/api/types';
import type { TKey } from '@/i18n';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useOnline } from '@/features/upload/uploadStatus';
import { useServices } from '@/services';
import { Banner, Button } from '@/ui/components';
import { IconTile, type IconTileTone } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { StatusPill } from '@/ui/StatusPill';
import { useTheme, type Theme } from '@/ui/theme';
import { iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

import {
  defaultMinutesLang,
  failedText,
  MINUTES_LANG_NAME,
  MINUTES_LANGS,
  minutesNotes,
  minutesProblem,
  minutesProblemAction,
  minutesProblemText,
  minutesSlot,
  minutesWarnings,
  pollMinutes,
  upsertMinutes,
  type MinutesProblem,
  type MinutesShareFormat,
  type MinutesStage,
} from './minutesModel';
import { downloadForShare, nativeShare, placeForShare } from './shareFile';

export interface MinutesSheetProps {
  visible: boolean;
  onClose: () => void;
  meetingId: string;
  /** Yig'ilish sarlavhasi: varaq tepasida va fayl nomining zaxirasi. */
  title: string;
  /** Yig'ilish tili - hujjat tilining default'i shundan. */
  meetingLanguage: Lang;
}

const FORMATS: { value: MinutesShareFormat; title: TKey; hint: TKey; icon: LucideIcon; tone: IconTileTone }[] = [
  { value: 'docx', title: 'share.fmt.docx', hint: 'share.fmt.docxHint', icon: FileType, tone: 'info' },
  { value: 'pdf', title: 'share.fmt.pdf', hint: 'share.fmt.pdfHint', icon: FileText, tone: 'bad' },
];

// Oxirgi tanlangan format - ilova ochiq turganda eslab qolinadi (ExportSheet kabi). Sozlamaga
// yozilmaydi: bu qulaylik, holat emas. Til esa har safar yig'ilish tilidan (server qoidasi).
let lastFormat: MinutesShareFormat = 'docx';

function rememberFormat(f: MinutesShareFormat): void {
  lastFormat = f;
}

/** Testlar uchun: eslab qolingan formatni tozalash. */
export function resetMinutesMemory(): void {
  lastFormat = 'docx';
}

interface Problem {
  p: MinutesProblem;
  stage: MinutesStage;
  /** `create` qaytarilganda - o'sha `force` bilan. */
  force?: boolean;
  /** `export` qaytarilganda - o'sha format bilan. */
  format?: MinutesShareFormat;
}

/** So'rash to'xtagan hujjat: 10 daqiqa o'tdi yoki davom etib bo'lmaydigan xato (403...). */
interface PollStop {
  id: string;
  kind: 'timeout' | 'fatal';
}

type Phase = 'loading' | 'idle' | 'running' | 'stopped' | 'failed' | 'ready';

export function MinutesSheet(props: MinutesSheetProps) {
  // Ichki qism faqat ochiq paytda mount bo'ladi: har ochilishda ro'yxat qaytadan o'qiladi
  // (server ishi davom etgan bo'lishi mumkin), yopilganda so'rash va yuklash to'xtaydi.
  return (
    <Modal visible={props.visible} transparent animationType="slide" onRequestClose={props.onClose} statusBarTranslucent>
      {props.visible ? <MinutesBody {...props} /> : null}
    </Modal>
  );
}

function MinutesBody({ onClose, meetingId, title, meetingLanguage }: MinutesSheetProps) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const insets = useSafeInsets();
  const { meetings, session } = useServices();
  const uiLang = useSettings((x) => x.uiLang);
  const online = useOnline();

  const [lang, setLang] = useState<MinutesLanguage>(() => defaultMinutesLang(meetingLanguage));
  const [format, setFormat] = useState<MinutesShareFormat>(lastFormat);
  // null - ro'yxat hali kelmadi (birinchi ochilish).
  const [items, setItems] = useState<MinutesView[] | null>(null);
  const [listing, setListing] = useState(true);
  const [busy, setBusy] = useState<'create' | 'share' | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [pollStop, setPollStop] = useState<PollStop | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const alive = useRef(true);
  // Har so'rovning raqami: kech kelgan (eskirgan) javob yangi holatni buzmasin.
  const listRun = useRef(0);
  const actRun = useRef(0);
  // Joriy fayl yuklash: varaq yopilsa native yuklash ham to'xtaydi (ExportSheet kabi).
  const download = useRef<AbortController | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      download.current?.abort();
    };
  }, []);

  /** Ro'yxat javobini holatga yozadi - faqat eng oxirgi so'rovniki (eskisi yangisini bosmasin). */
  const settleList = useCallback((mine: number, res: { ok: true; items: MinutesView[] } | { ok: false; err: unknown }) => {
    if (!alive.current || mine !== listRun.current) return;
    setListing(false);
    if (res.ok) {
      setItems(res.items);
      setProblem((prev) => (prev?.stage === 'list' ? null : prev));
    } else {
      // Ro'yxat kelmadi - "Tayyorlash" baribir ishlaydi: tayyor hujjat bo'lsa server o'zi qaytaradi.
      setItems((prev) => prev ?? []);
      setProblem({ p: minutesProblem(res.err, 'list'), stage: 'list' });
    }
  }, []);

  // Holat faqat javob kelganda (`.then`) yoziladi - ImportScreen kabi; effekt ichida sinxron setState yo'q.
  const requestList = useCallback(() => {
    const mine = ++listRun.current;
    meetings.minutesList(meetingId).then(
      (r) => settleList(mine, { ok: true, items: Array.isArray(r?.items) ? r.items : [] }),
      (err: unknown) => settleList(mine, { ok: false, err }),
    );
  }, [meetings, meetingId, settleList]);

  // Ochilishda ro'yxat (`listing` boshidan true): server ishi davom etgan bo'lsa shu yerdan davom etamiz.
  useEffect(() => {
    requestList();
  }, [requestList]);

  const reloadList = useCallback(() => {
    setListing(true);
    requestList();
  }, [requestList]);

  /**
   * Aniq hujjat serverda yo'q (`minutes_not_found`): darhol ro'yxatdan olib tashlanadi (varaq
   * "Tayyorlash"ga qaytadi) va ro'yxat qayta o'qiladi - yangiroq qator bo'lsa o'shani ko'rsatadi.
   */
  const forget = useCallback(
    (id: string) => {
      setItems((prev) => (prev ?? []).filter((x) => x.id !== id));
      reloadList();
    },
    [reloadList],
  );

  const slot = useMemo(() => minutesSlot(items, lang), [items, lang]);
  const runningId = slot.running?.id ?? null;
  const stopped = pollStop != null && pollStop.id === runningId ? pollStop : null;
  const isStopped = stopped != null;

  // Yozilayotgan hujjatni so'rab turish. Qayta tekshirish (`pollStop` tozalanadi) - yangi 10 daqiqa.
  useEffect(() => {
    if (!runningId || isStopped) return;
    return pollMinutes(() => meetings.minutes(meetingId, runningId), {
      onUpdate: (v) => {
        if (!alive.current) return;
        setItems((prev) => upsertMinutes(prev, v));
        setProblem((prev) => (prev?.stage === 'poll' ? null : prev));
      },
      onTransient: (e) => {
        // Internet uzildi va h.k.: so'rash davom etadi, sababi ko'rinib turadi.
        if (alive.current) setProblem({ p: minutesProblem(e, 'poll'), stage: 'poll' });
      },
      onFatal: (e) => {
        if (!alive.current) return;
        const p = minutesProblem(e, 'poll');
        setProblem({ p, stage: 'poll' });
        if (p.kind === 'gone') forget(runningId);
        else setPollStop({ id: runningId, kind: 'fatal' });
      },
      onTimeout: () => {
        if (alive.current) setPollStop({ id: runningId, kind: 'timeout' });
      },
    });
  }, [runningId, isStopped, meetings, meetingId, forget]);

  const ready = slot.ready;
  const phase: Phase =
    items === null ? 'loading' : slot.running ? (isStopped ? 'stopped' : 'running') : slot.failed ? 'failed' : ready ? 'ready' : 'idle';
  const locked = busy !== null || listing;
  // Eski server (bayonnoma yo'llari yo'q): "Tayyorlash" ham baribir 404 - tugma qayta urinishga undamaydi.
  const notOnServer = problem?.p.kind === 'notOnServer';

  const pickLang = (l: MinutesLanguage) => {
    setLang(l);
    // Boshqa tilning xatosi bu tilga tegishli emas; ro'yxat xatosi esa umumiy - qoladi.
    setProblem((prev) => (prev?.stage === 'list' ? prev : null));
  };

  const pickFormat = (f: MinutesShareFormat) => {
    rememberFormat(f);
    setFormat(f);
    setProblem((prev) => (prev?.stage === 'export' ? null : prev));
  };

  const prepare = async (force: boolean) => {
    const mine = ++actRun.current;
    setBusy('create');
    setProblem(null);
    setPollStop(null);
    try {
      const v = await meetings.createMinutes(meetingId, { language: lang, force });
      if (!alive.current) return;
      // `running` (202 yoki 200) - ro'yxatga tushgach so'rash effekti o'zi boshlanadi.
      setItems((prev) => upsertMinutes(prev, v));
    } catch (e) {
      if (alive.current && mine === actRun.current) setProblem({ p: minutesProblem(e, 'create'), stage: 'create', force });
    } finally {
      if (alive.current && mine === actRun.current) setBusy(null);
    }
  };

  const share = async (doc: MinutesView, fmt: MinutesShareFormat) => {
    const mine = ++actRun.current;
    const current = () => alive.current && mine === actRun.current;
    download.current?.abort();
    const ctl = new AbortController();
    download.current = ctl;
    setBusy('share');
    setProgress(null);
    setProblem(null);
    try {
      const nat = nativeShare();
      if (!(await nat.canShare())) {
        if (current()) setProblem({ p: { kind: 'cannotShare' }, stage: 'export', format: fmt });
        return;
      }
      const { res, dir } = await downloadForShare(nat, meetings.minutesExportUrl(meetingId, doc.id, fmt), {
        tokens: session,
        language: uiLang,
        signal: ctl.signal,
        onProgress: (p) => {
          if (current() && p.total > 0) setProgress(Math.min(100, Math.round((p.written / p.total) * 100)));
        },
      });
      const type = SHARE_FILE_TYPES[fmt];
      // Server haqiqiy nomni beradi ("Баённома - <sarlavha> <sana>.docx"); bo'lmasa - "Bayonnoma - <sarlavha>".
      const fallback = title ? `${t('minutes.title')} - ${title}` : t('minutes.title');
      const name = fileNameFromDisposition(headerOf(res.headers, 'Content-Disposition'), fallback, type.ext);
      const target = await placeForShare(nat, dir, res.uri, name);
      if (!current()) return;
      await nat.share(target, type.mime, title || name);
      if (current()) onClose();
    } catch (e) {
      if (!current()) return;
      const p = minutesProblem(e, 'export');
      setProblem({ p, stage: 'export', format: fmt });
      if (p.kind === 'gone') forget(doc.id);
    } finally {
      if (download.current === ctl) download.current = null;
      if (current()) {
        setBusy(null);
        setProgress(null);
      }
    }
  };

  /** "Qayta tekshirish": ro'yxat qayta o'qiladi; hali yozilayotgan bo'lsa so'rash yangidan boshlanadi. */
  const recheck = () => {
    setPollStop(null);
    setProblem(null);
    reloadList();
  };

  // So'rashdagi o'tkinchi xatoda tugma yo'q - so'rash o'zi davom etadi.
  const next = problem && problem.stage !== 'poll' ? minutesProblemAction(problem.p) : null;
  const runNext = () => {
    if (!problem || !next) return;
    if (next === 'recheck') recheck();
    else if (next === 'useDocx' || next === 'usePdf') {
      const f: MinutesShareFormat = next === 'useDocx' ? 'docx' : 'pdf';
      pickFormat(f);
      if (ready) void share(ready, f);
    } else if (problem.stage === 'list') reloadList();
    else if (problem.stage === 'create') void prepare(problem.force ?? false);
    else if (problem.stage === 'export' && ready) void share(ready, problem.format ?? format);
  };
  const nextTitle: TKey | null = next === 'useDocx' ? 'share.useDocx' : next === 'usePdf' ? 'share.usePdf' : next === 'recheck' ? 'minutes.check' : next ? 'common.retry' : null;

  return (
    <View style={s.backdrop}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel={t('common.close')} />
      <View style={[s.sheet, { paddingBottom: Math.max(insets.bottom, 12) }]} testID="minutes-sheet">
        <View style={s.grabber} />
        <View style={s.head}>
          <View style={s.headText}>
            <Text style={[typeScale.headline, { color: th.text }]} accessibilityRole="header">
              {t('minutes.title')}
            </Text>
            <Text style={[typeScale.caption, { color: th.textMuted }]} numberOfLines={2}>
              {title ? `${title} · ${t('minutes.lead')}` : t('minutes.lead')}
            </Text>
          </View>
          <Pressable
            testID="minutes-close"
            onPress={onClose}
            hitSlop={10}
            accessibilityRole="button"
            accessibilityLabel={t('common.close')}
            style={s.close}>
            <X size={iconSize.sm} color={th.textSoft} strokeWidth={stroke.small} />
          </Pressable>
        </View>

        <ScrollView style={s.scroll} contentContainerStyle={s.scrollBody} keyboardShouldPersistTaps="handled">
          <ListGroup header={t('minutes.language')}>
            {MINUTES_LANGS.map((l) => (
              <ListRow
                key={l}
                testID={`minutes-lang-${l}`}
                title={MINUTES_LANG_NAME[l]}
                right={{ kind: 'check', checked: lang === l }}
                onPress={() => pickLang(l)}
                disabled={busy !== null}
              />
            ))}
          </ListGroup>

          <ListGroup header={t('share.formats')}>
            {FORMATS.map((f) => (
              <ListRow
                key={f.value}
                testID={`minutes-fmt-${f.value}`}
                title={t(f.title)}
                subtitle={t(f.hint)}
                leading={<IconTile icon={f.icon} tone={f.tone} size="sm" />}
                right={{ kind: 'check', checked: format === f.value }}
                onPress={() => pickFormat(f.value)}
                disabled={busy !== null}
              />
            ))}
          </ListGroup>

          {phase === 'running' ? (
            <View testID="minutes-running" style={[s.card, s.row]} accessibilityLiveRegion="polite">
              <ActivityIndicator color={th.textMuted} />
              <View style={s.flex}>
                <Text style={[typeScale.rowTitle, { color: th.text }]}>{t('minutes.running')}</Text>
                <Text style={[typeScale.caption, { color: th.textMuted }]}>{t('minutes.runningHint')}</Text>
              </View>
            </View>
          ) : null}
          {stopped?.kind === 'timeout' ? <Banner testID="minutes-slow" tone="warn" text={t('minutes.slow')} /> : null}
          {phase === 'failed' && slot.failed ? <Banner testID="minutes-failed" tone="bad" text={failedText(t, slot.failed)} /> : null}
          {ready && (phase === 'ready' || phase === 'failed') ? <ReadyCard view={ready} /> : null}
          {phase === 'idle' && slot.staleOnly ? <Banner testID="minutes-stale" tone="neutral" text={t('minutes.stale')} /> : null}

          {problem ? (
            <Banner
              testID="minutes-problem"
              tone={problem.p.kind === 'error' || problem.p.kind === 'final' ? 'bad' : 'warn'}
              text={minutesProblemText(t, problem.p)}
              action={nextTitle ? { title: t(nextTitle), onPress: runNext } : undefined}
            />
          ) : online === false ? (
            <Banner testID="minutes-offline" tone="warn" text={t('minutes.offline')} />
          ) : null}
        </ScrollView>

        <View style={s.footer}>
          {busy === 'share' ? (
            <View style={s.status} accessibilityLiveRegion="polite">
              <ActivityIndicator size="small" color={th.textMuted} />
              <Text style={[typeScale.caption, { color: th.textMuted }]} testID="minutes-status">
                {progress != null ? t('share.progress', { pct: progress }) : t('share.preparing')}
              </Text>
            </View>
          ) : null}
          {ready && (phase === 'ready' || phase === 'failed') ? (
            <>
              <Button
                testID="minutes-share"
                title={t('share.send')}
                icon={Share2}
                pill
                loading={busy === 'share'}
                disabled={locked}
                onPress={() => void share(ready, format)}
              />
              {/* Tayyor hujjat ustidan qayta yozish; oxirgi urinish yiqilgan bo'lsa - shu urinishni qaytarish. */}
              <Button
                testID="minutes-redo"
                variant="ghost"
                pill
                title={phase === 'failed' ? t('common.retry') : t('minutes.redo')}
                loading={busy === 'create'}
                disabled={locked}
                onPress={() => void prepare(true)}
              />
            </>
          ) : phase === 'stopped' ? (
            <Button testID="minutes-recheck" title={t('minutes.check')} icon={RotateCcw} variant="secondary" pill loading={listing} onPress={recheck} />
          ) : phase === 'failed' ? (
            <Button
              testID="minutes-retry"
              title={t('common.retry')}
              icon={RotateCcw}
              pill
              loading={busy === 'create'}
              disabled={locked}
              onPress={() => void prepare(false)}
            />
          ) : (
            // Ro'yxat o'qilayotganda va hujjat yozilayotganda - aylanma (bosib bo'lmaydi).
            <Button
              testID="minutes-prepare"
              title={t('minutes.prepare')}
              icon={FilePen}
              pill
              loading={phase === 'loading' || phase === 'running' || busy === 'create'}
              disabled={locked || phase !== 'idle' || notOnServer}
              onPress={() => void prepare(false)}
            />
          )}
        </View>
      </View>
    </View>
  );
}

/** Tayyor hujjat: bo'lim/band soni, LOYIHA belgisi, model izohlari va ogohlantirishlar soni. */
function ReadyCard({ view }: { view: MinutesView }) {
  const t = useT();
  const th = useTheme();
  const s = useMemo(() => makeStyles(th), [th]);
  const notes = minutesNotes(view.notes);
  const warnings = minutesWarnings(view.warnings);
  return (
    <View testID="minutes-ready" style={s.card}>
      <View style={s.row}>
        <IconTile icon={FileCheck} tone="good" size="sm" />
        <Text style={[typeScale.rowTitle, s.flex, { color: th.text }]}>
          {t('minutes.ready', { sections: view.sectionCount, items: view.itemCount })}
        </Text>
        <StatusPill label={t('minutes.draftPill')} tone="warn" />
      </View>
      <Text testID="minutes-draft" style={[typeScale.caption, { color: th.textMuted }]}>
        {t('minutes.draft')}
      </Text>
      {notes.length ? (
        <View testID="minutes-notes" style={s.notes}>
          <Text style={[typeScale.label, { color: th.text }]}>{t('minutes.notes')}</Text>
          {notes.map((n) => (
            <Text key={n} style={[typeScale.caption, { color: th.textSoft }]}>
              {`• ${n}`}
            </Text>
          ))}
        </View>
      ) : null}
      {warnings.length ? (
        <Text testID="minutes-warnings" style={[typeScale.caption, { color: th.tones.warn.fg }]}>
          {t('minutes.warnings', { n: warnings.length })}
        </Text>
      ) : null}
    </View>
  );
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
    // Banner kabi pastki bo'shliq (`marginBottom: 10`) - holat kartasi va bannerlar bir ritmda.
    card: { backgroundColor: th.surfaceAlt, borderRadius: radius.lg, padding: 14, gap: 8, marginBottom: 10 },
    row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
    flex: { flex: 1, minWidth: 0 },
    notes: { gap: 2 },
    footer: { paddingHorizontal: 16, paddingTop: 8, gap: 8 },
    status: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  });
}
