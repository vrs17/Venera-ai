/**
 * Pastki pleer paneli (spec 3.2): ekran pastida doim turadi (scroll'dan tashqarida),
 * transkriptni yopmaydi. Boshqaruv: tezlik, -15 s, ijro/pauza, +15 s, sudrab
 * o'tkaziladigan chiziq.
 *
 * Manba ustuvorligi (egasi: "yozilganini qayerda eshitaman?"):
 *  1. TELEFONDAGI fayl (hali yuklanmagan yoki 7 kun saqlanayotgan yozuv) - darhol,
 *     internetsiz va trafiksiz ishlaydi;
 *  2. aks holda serverdagi audio (`GET /meetings/{id}/audio`, Bearer bilan; Range);
 *  3. aks holda pleer yo'q - bir qatorli izoh.
 *
 * Manba tashrif davomida BARQAROR: ijro boshlangach tanlov qulflanadi. Aks holda yuklash
 * tugashi (yoki 10 s lik polling) pleerni almashtirib, eshitilayotgan yozuvni 0:00 ga
 * qaytarib to'xtatardi.
 *
 * `seek` prop: xulosa dalili yoki transkript pufakchasi bosilganda shu soniyaga
 * o'tib ijro etadi.
 *
 * Sudrash: PanResponder (gesture-handler/reanimated qo'shilmaydi - spec 0).
 */
import { useAudioPlayer, useAudioPlayerStatus, type AudioSource } from 'expo-audio';
import { Pause, Play, RotateCcw, RotateCw, Smartphone, VolumeX, type LucideIcon } from 'lucide-react-native';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, PanResponder, Pressable, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';

import type { Meeting } from '@/api/types';
import { useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { useServices } from '@/services';
import { useSafeInsets } from '@/ui/insets';
import { useTheme } from '@/ui/theme';
import { hit, iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

import { formatClock } from './formatDate';
import { clearPlayback, holdFile, reportPlayback, usePlayback } from './playback';

export interface SeekRequest {
  t: number;
  n: number;
}

/** Tezliklar aylanasi: 1 -> 1.25 -> 1.5 -> 2 -> 0.75 -> 1. */
export const SPEEDS = [1, 1.25, 1.5, 2, 0.75] as const;
/** Oldinga/orqaga qadam, soniya (podkast ilovalari kabi). */
export const SKIP_SEC = 15;

export type AudioChoice =
  | { kind: 'remote'; meetingId: string }
  | { kind: 'local'; uri: string }
  | { kind: 'checking' }
  | { kind: 'none'; reason: 'expired' | 'missing' | 'unavailable' | 'recording' };

/** Bosilgan siljitish shundan eski bo'lsa yangi pleerda qayta ishlatilmaydi (ms). */
const STALE_SEEK_MS = 1500;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Telefondagi fayl bormi (va bo'sh emasmi). null - tekshirilmoqda yoki uri yo'q. */
export function useFileExists(uri: string | null): boolean | null {
  const { files } = useServices();
  const [state, setState] = useState<{ uri: string | null; exists: boolean | null }>({ uri: null, exists: null });
  useEffect(() => {
    if (!uri) return;
    let alive = true;
    files
      .size(uri)
      .then((size) => alive && setState({ uri, exists: size != null && size > 0 }))
      .catch(() => alive && setState({ uri, exists: false }));
    return () => {
      alive = false;
    };
  }, [uri, files]);
  return uri && state.uri === uri ? state.exists : null;
}

/** Toza tanlov (yuqoridagi ustuvorlik): telefondagi fayl, keyin server, keyin izoh. */
export function pickAudio(m: Meeting | null, row: QueueRow | null, exists: boolean | null): AudioChoice {
  // Yozilayotgan fayl hali ochiq - uni o'qimaymiz, pleer ham ko'rsatilmaydi.
  if (row?.state === 'recording') return { kind: 'none', reason: 'recording' };
  const localUri = row ? row.fileUri : null;
  if (localUri && exists) return { kind: 'local', uri: localUri };
  if (localUri && exists === null) return { kind: 'checking' };
  if (m?.upload.complete && m.audioAvailable) return { kind: 'remote', meetingId: m.id };
  if (m?.upload.complete && !m.audioAvailable) return { kind: 'none', reason: 'expired' };
  return { kind: 'none', reason: localUri ? 'missing' : 'unavailable' };
}

function choiceId(c: AudioChoice): string | null {
  if (c.kind === 'local') return `local:${c.uri}`;
  if (c.kind === 'remote') return `remote:${c.meetingId}`;
  return null;
}

/**
 * Sahifa uchun audio manbasi. Ijro bir marta boshlangach (`usePlayback.started`) tanlov
 * shu tashrif oxirigacha qulflanadi: yuklash tugadi, polling yangi `Meeting` keltirdi
 * yoki navbat qatori o'zgardi - eshitilayotgan pleer almashmaydi.
 */
export function useAudioChoice(m: Meeting | null, row: QueueRow | null, playbackKey: string | null): AudioChoice {
  const localUri = row && row.state !== 'recording' ? row.fileUri : null;
  const exists = useFileExists(localUri);
  const fresh = pickAudio(m, row, exists);
  const freshId = choiceId(fresh);
  const started = usePlayback((p) => p.started && p.key != null && p.key === playbackKey);
  const [locked, setLocked] = useState<AudioChoice | null>(null);
  // Render paytidagi hosila holat (React ruxsat bergan naqsh): effekt kutilmaydi, bitta kadr ham almashmaydi.
  if (!locked && started && freshId) setLocked(fresh);
  return locked ?? fresh;
}

/**
 * Tanlangan manba bo'yicha pastki panel. `expired` - banner sahifaning o'zida
 * (`detail.audioExpired`), bu yerda takrorlanmaydi.
 */
export function AudioDock({
  choice,
  seek,
  playbackKey,
  durationHint,
}: {
  choice: AudioChoice;
  seek: SeekRequest | null;
  playbackKey: string;
  durationHint?: number | null;
}) {
  const t = useT();
  if (choice.kind === 'remote')
    return <RemotePlayer key={choice.meetingId} meetingId={choice.meetingId} seek={seek} playbackKey={playbackKey} durationHint={durationHint} />;
  if (choice.kind === 'local')
    return <PlayerDock key={choice.uri} source={{ uri: choice.uri }} local seek={seek} playbackKey={playbackKey} durationHint={durationHint} />;
  if (choice.kind === 'none' && choice.reason === 'missing') return <DockNote text={t('recs.fileMissing')} />;
  if (choice.kind === 'none' && choice.reason === 'unavailable') return <DockNote text={t('player.unavailable')} />;
  return null;
}

/** Server audio: token olinadi va `{uri, headers}` (format testda qat'iy tekshiriladi). */
export function RemotePlayer({
  meetingId,
  seek,
  playbackKey,
  durationHint,
}: {
  meetingId: string;
  seek: SeekRequest | null;
  playbackKey: string;
  durationHint?: number | null;
}) {
  const t = useT();
  const { session, meetings } = useServices();
  const [source, setSource] = useState<AudioSource>(null);
  const [tokenFailed, setTokenFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    session
      .getToken()
      .then((token) => {
        if (alive) setSource({ uri: meetings.audioUrl(meetingId), headers: { Authorization: `Bearer ${token}`, 'X-Venera-Client': 'mobile' } });
      })
      // Token olinmadi (internet yo'q, sessiya tugagan) - panel jim yo'qolmasin, sababini aytadi.
      .catch(() => alive && setTokenFailed(true));
    return () => {
      alive = false;
    };
  }, [meetingId, meetings, session]);

  if (tokenFailed) return <DockNote testID="player-error" text={t('recs.audioFailed')} />;
  if (!source) return null;
  return <PlayerDock source={source} seek={seek} playbackKey={playbackKey} durationHint={durationHint} />;
}

/** Pleer o'rnida bir qatorli izoh (fayl topilmadi / audio yo'q). */
export function DockNote({ text, testID = 'player-note' }: { text: string; testID?: string }) {
  const th = useTheme();
  const insets = useSafeInsets();
  return (
    <View testID={testID} style={[s.dock, s.note, { borderTopColor: th.border, backgroundColor: th.bg, paddingBottom: insets.bottom + 12 }]}>
      <VolumeX size={iconSize.sm} color={th.textMuted} strokeWidth={stroke.small} />
      <Text style={[typeScale.caption, { color: th.textMuted, flexShrink: 1 }]}>{text}</Text>
    </View>
  );
}

export function PlayerDock({
  source,
  local,
  seek,
  playbackKey,
  durationHint,
}: {
  source: AudioSource;
  /** Telefondagi fayl - o'ngda telefon belgisi. */
  local?: boolean;
  seek: SeekRequest | null;
  playbackKey: string;
  /** Fayl hali o'qilmagan paytda ko'rsatiladigan davomiylik (server/qatordan). */
  durationHint?: number | null;
}) {
  const th = useTheme();
  const t = useT();
  const insets = useSafeInsets();
  const player = useAudioPlayer(source, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);
  const [rate, setRate] = useState<number>(1);
  const [width, setWidth] = useState(1);
  const [preview, setPreview] = useState<number | null>(null);
  // "Play" bosildi, audio hali yuklanmoqda - tugmada aylanma (aks holda bosish ishlamagandek ko'rinadi).
  const [wantPlay, setWantPlay] = useState(false);
  if (wantPlay && status.playing) setWantPlay(false);
  const waiting = (wantPlay && (!status.isLoaded || !!status.isBuffering)) || (!!status.playing && !!status.isBuffering);
  // Pleer yangidan ochilganda (manba almashdi) eski bosish uni o'zi ijro ettirib yubormasin.
  const mountSeek = useRef(seek);
  const localUri = local && source && typeof source === 'object' && typeof source.uri === 'string' ? source.uri : null;

  useEffect(() => (localUri ? holdFile(localUri) : undefined), [localUri]);

  const duration = status.duration > 0 ? status.duration : 0;
  const shownDuration = duration || durationHint || 0;
  const pos = clamp(status.currentTime || 0, 0, duration || Number.MAX_SAFE_INTEGER);
  const ratio = preview ?? (duration > 0 ? pos / duration : 0);

  const seekTo = (sec: number) => {
    void Promise.resolve(player.seekTo(clamp(sec, 0, duration || Math.max(0, sec)))).catch(() => {});
  };

  useEffect(() => {
    if (!seek) return;
    if (seek === mountSeek.current && Date.now() - seek.n > STALE_SEEK_MS) return;
    setWantPlay(true);
    void Promise.resolve(player.seekTo(seek.t))
      .then(() => player.play())
      .catch(() => {});
  }, [seek, player]);

  // Yangi pleer (manba almashdi) eski tezlikni bilmaydi - qayta beramiz.
  useEffect(() => {
    if (rate === 1) return;
    try {
      player.setPlaybackRate(rate);
    } catch {
      /* eski native modul - tezlik o'zgarmaydi, ijro davom etadi */
    }
  }, [player, rate]);

  useEffect(() => {
    reportPlayback(playbackKey, pos, !!status.playing);
  }, [playbackKey, pos, status.playing]);
  useEffect(() => () => clearPlayback(playbackKey), [playbackKey]);

  // Davomiylik/kenglik o'zgarsa (yuklangach bir marta) qayta yaratiladi.
  const pan = useMemo(
    () =>
      createScrubber({
        width,
        onPreview: setPreview,
        onCommit: (r) => {
          if (duration > 0) void Promise.resolve(player.seekTo(r * duration)).catch(() => {});
        },
      }),
    [duration, width, player],
  );

  const togglePlay = () => {
    if (status.playing || waiting) {
      setWantPlay(false);
      player.pause();
      return;
    }
    setWantPlay(true);
    // Oxiriga yetgan bo'lsa - boshidan (aks holda "Play" hech narsa qilmagandek ko'rinadi).
    if (duration > 0 && pos >= duration - 0.3) {
      void Promise.resolve(player.seekTo(0))
        .then(() => player.play())
        .catch(() => {});
      return;
    }
    player.play();
  };

  const cycleSpeed = () => {
    const i = SPEEDS.findIndex((x) => x === rate);
    const next = SPEEDS[(i + 1) % SPEEDS.length];
    setRate(next);
    try {
      player.setPlaybackRate(next);
    } catch {
      /* yuqoridagi kabi */
    }
  };

  const speedLabel = `${rate}x`;
  const shownPos = preview != null ? preview * duration : pos;
  const timeStyle = [s.time, { color: th.textMuted }];

  return (
    <View testID="player-dock" style={[s.dock, { borderTopColor: th.border, backgroundColor: th.bg, paddingBottom: insets.bottom + 8 }]}>
      {status.error ? (
        // Pleer qoladi: "Play" qayta urinadi (xato yangi yuklashda o'zi tozalanadi).
        <Text testID="player-error" numberOfLines={2} style={[typeScale.caption, s.error, { color: th.tones.bad.fg }]}>
          {local ? t('recs.fileFailed') : t('recs.audioFailed')}
        </Text>
      ) : null}
      <View style={s.trackRow}>
        <Text style={[timeStyle, s.timeLeft]}>{formatClock(shownPos)}</Text>
        <View
          testID="player-track"
          {...pan.panHandlers}
          // TalkBack: sozlanadigan element - yuqoriga/pastga surish 15 s siljitadi.
          accessible
          accessibilityRole="adjustable"
          accessibilityLabel={t('player.position')}
          accessibilityValue={{ min: 0, max: Math.round(duration), now: Math.round(pos), text: `${formatClock(pos)} / ${formatClock(shownDuration)}` }}
          accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
          onAccessibilityAction={(e) => {
            if (e.nativeEvent.actionName === 'increment') seekTo(pos + SKIP_SEC);
            if (e.nativeEvent.actionName === 'decrement') seekTo(pos - SKIP_SEC);
          }}
          onLayout={(e: LayoutChangeEvent) => setWidth(Math.max(1, e.nativeEvent.layout.width))}
          // Chiziq 32 dp - barmoq uchun 48 dp gacha kengaytiramiz (44 dp minimum).
          hitSlop={TRACK_SLOP}
          style={s.trackArea}>
          {/* Ichki qismlar barmoqni olmaydi: locationX doim butun chiziqqa nisbatan bo'lsin. */}
          <View pointerEvents="none" style={[s.line, { backgroundColor: th.border }]}>
            <View style={[s.fill, { width: `${ratio * 100}%`, backgroundColor: th.primary }]} />
          </View>
          <View
            pointerEvents="none"
            style={[
              s.thumb,
              { left: clamp(ratio * width, 0, width) - THUMB / 2, backgroundColor: th.primary, transform: [{ scale: preview != null ? 1.3 : 1 }] },
            ]}
          />
        </View>
        <Text style={[timeStyle, s.timeRight]}>{shownDuration > 0 ? formatClock(shownDuration) : '--:--'}</Text>
      </View>

      <View style={s.controls}>
        <Pressable
          testID="player-speed"
          accessibilityRole="button"
          accessibilityLabel={t('recs.speed', { x: speedLabel })}
          onPress={cycleSpeed}
          hitSlop={6}
          style={({ pressed }) => [s.speed, { backgroundColor: pressed ? th.border : th.surfaceAlt }]}>
          <Text style={[typeScale.label, s.tabular, { color: th.text }]}>{speedLabel}</Text>
        </Pressable>

        <View style={s.center}>
          <SkipButton testID="player-back" icon={RotateCcw} label={t('recs.back15')} onPress={() => seekTo(pos - SKIP_SEC)} />
          <Pressable
            testID="player-play"
            accessibilityRole="button"
            accessibilityLabel={status.playing ? t('player.pause') : t('player.play')}
            accessibilityState={{ busy: waiting }}
            onPress={togglePlay}
            style={({ pressed }) => [s.play, { backgroundColor: th.primary, opacity: pressed ? 0.85 : 1 }]}>
            {waiting ? (
              <ActivityIndicator testID="player-buffering" color={th.primaryText} />
            ) : status.playing ? (
              <Pause size={iconSize.lg} color={th.primaryText} fill={th.primaryText} strokeWidth={stroke.regular} />
            ) : (
              // Uchburchak optik markazda tursin - 2 px o'ngga.
              <Play size={iconSize.lg} color={th.primaryText} fill={th.primaryText} strokeWidth={stroke.regular} style={s.playNudge} />
            )}
          </Pressable>
          <SkipButton testID="player-fwd" icon={RotateCw} label={t('recs.fwd15')} onPress={() => seekTo(pos + SKIP_SEC)} />
        </View>

        {local ? (
          <View testID="player-local" accessible accessibilityLabel={t('recs.localFile')} style={s.side}>
            <View style={[s.localBadge, { backgroundColor: th.surfaceAlt }]}>
              <Smartphone size={iconSize.sm} color={th.textSoft} strokeWidth={stroke.small} />
            </View>
          </View>
        ) : (
          // Simmetriya: tezlik tugmasi bilan bir xil kenglik.
          <View style={s.side} />
        )}
      </View>
    </View>
  );
}

/**
 * Chiziqni sudrash: barmoq tekkan joydan boshlab, qo'yib yuborilganda o'tadi.
 * Komponentdan TASHQARIDA: gesture holati (boshlang'ich x, joriy ulush) oddiy
 * o'zgaruvchilarda turadi - render paytida hech narsa o'qilmaydi.
 */
function createScrubber(o: { width: number; onPreview: (ratio: number | null) => void; onCommit: (ratio: number) => void }) {
  let startX = 0;
  let current: number | null = null;
  const update = (x: number) => {
    current = clamp(x / Math.max(1, o.width), 0, 1);
    o.onPreview(current);
  };
  const end = (commit: boolean) => {
    const r = current;
    current = null;
    o.onPreview(null);
    if (commit && r != null) o.onCommit(r);
  };
  return PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    // Sudrash paytida ota ko'rinish barmoqni tortib olmasin.
    onPanResponderTerminationRequest: () => false,
    onPanResponderGrant: (e) => {
      startX = e.nativeEvent.locationX;
      update(startX);
    },
    onPanResponderMove: (_e, g) => update(startX + g.dx),
    onPanResponderRelease: () => end(true),
    onPanResponderTerminate: () => end(false),
  });
}

/**
 * Aylanma strelka ichida "15". Belgi 28 px (spec 22 dan katta): 22 px ichida "15"
 * chiziqqa tegib qolardi va kichik ekranda o'qilmasdi.
 */
function SkipButton({ icon: Icon, label, onPress, testID }: { icon: LucideIcon; label: string; onPress: () => void; testID: string }) {
  const th = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={4}
      style={({ pressed }) => [s.skip, { backgroundColor: pressed ? th.surfaceAlt : 'transparent' }]}>
      <Icon size={iconSize.xl} color={th.text} strokeWidth={stroke.regular} />
      <Text style={[s.skipText, { color: th.text }]}>{SKIP_SEC}</Text>
    </Pressable>
  );
}

const THUMB = 14;
const TRACK_SLOP = { top: 8, bottom: 8 };

const s = StyleSheet.create({
  dock: { borderTopWidth: StyleSheet.hairlineWidth, paddingHorizontal: 16, paddingTop: 8 },
  note: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingTop: 12 },
  error: { paddingBottom: 4 },
  trackRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  trackArea: { flex: 1, height: 32, justifyContent: 'center' },
  line: { height: 4, borderRadius: 2, overflow: 'hidden' },
  fill: { height: 4, borderRadius: 2 },
  thumb: { position: 'absolute', width: THUMB, height: THUMB, borderRadius: THUMB / 2, top: (32 - THUMB) / 2 },
  time: { fontSize: 12, lineHeight: 16, fontVariant: ['tabular-nums'] },
  timeLeft: { minWidth: 40 },
  timeRight: { minWidth: 40, textAlign: 'right' },
  tabular: { fontVariant: ['tabular-nums'] },
  controls: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 2 },
  center: { flexDirection: 'row', alignItems: 'center', gap: 20 },
  side: { width: 52, height: hit.min, alignItems: 'center', justifyContent: 'center' },
  speed: { width: 52, height: 32, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  play: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  playNudge: { marginLeft: 2 },
  skip: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  skipText: { position: 'absolute', fontSize: 10, fontWeight: '700', fontVariant: ['tabular-nums'] },
  localBadge: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
});
