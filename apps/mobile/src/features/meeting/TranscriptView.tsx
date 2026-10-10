/**
 * Transkript tabi (spec 7.4): chat ko'rinishidagi dialog.
 *  - ketma-ket bir spiker segmentlari bitta pufakcha, har spikerning o'z rangi;
 *  - pufakchani bosish -> audio shu joydan; uzoq bosish -> matn/spikerni tuzatish;
 *  - spiker chiplari: nom berish, birlashtirish, taklif qilingan ismni qabul qilish;
 *  - qidiruv; TXT/SRT ulashish.
 *
 * Vaqt yorlig'i "▶ 12:34" ko'rinishida (ko'k) - pufakcha bosilsa shu joydan
 * eshitilishi bir qarashda bilinsin. Hozir eshitilayotgan pufakcha ajratib
 * ko'rsatiladi (`playback.ts`): faqat faol kalit tanlanadi, shuning uchun ro'yxat
 * har 250 ms emas, faqat pufakcha almashganda qayta chiziladi.
 */
import { Play } from 'lucide-react-native';
import { useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, Pressable, Share, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import type { Meeting, Segment, Speaker, Transcript } from '@/api/types';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Banner, Button, Field, Loading, Muted, styles as ui } from '@/ui/components';
import { errorText, shareableText, showToast } from '@/ui/errors';
import { PickerModal, PromptModal, type PickerOption } from '@/ui/modals';
import { useTheme } from '@/ui/theme';

import { formatClock } from './formatDate';
import { bubbleIndexAt, groupBubbles, searchBubbles, speakerColor, type Bubble } from './groupBubbles';
import { usePlayback } from './playback';
import { useMeetingMutations, useTranscript } from './queries';
import { speakerLabel, visibleSpeakers } from './renderTokens';

export interface TranscriptViewProps {
  meeting: Meeting;
  /** Tashqaridan (xulosa dalili) kelgan vaqt - shu pufakchaga aylantiriladi. */
  focus?: { t: number; n: number } | null;
  onSeek?: (t: number) => void;
}

type SpeakerAction = 'rename' | 'merge' | 'accept';
type SegmentEdit = { kind: 'text' | 'speaker'; seg: Segment };

export function TranscriptView({ meeting, focus, onSeek }: TranscriptViewProps) {
  const t = useT();
  const uiLang = useSettings((s) => s.uiLang);
  const q = useTranscript(meeting.id, meeting.transcript.available);
  const muts = useMeetingMutations(meeting.id);
  const { meetings } = useServices();
  const [query, setQuery] = useState('');
  const [speakerMenu, setSpeakerMenu] = useState<Speaker | null>(null);
  const [renaming, setRenaming] = useState<Speaker | null>(null);
  const [merging, setMerging] = useState<Speaker | null>(null);
  const [editBubble, setEditBubble] = useState<Bubble | null>(null);
  const [editSegment, setEditSegment] = useState<Segment | null>(null);
  const [respeaker, setRespeaker] = useState<Segment | null>(null);
  const listRef = useRef<FlatList<Bubble>>(null);

  const tr: Transcript | undefined = q.data;
  const speakers = useMemo(() => tr?.speakers ?? meeting.speakers, [tr, meeting.speakers]);
  const bubbles = useMemo(() => (tr ? groupBubbles(tr.segments, { speakers }) : []), [tr, speakers]);
  const matches = useMemo(() => searchBubbles(bubbles, query), [bubbles, query]);
  const shown = query.trim() ? matches.map((i) => bubbles[i]) : bubbles;
  // Faqat shu yig'ilish pleeri ijro etilgan bo'lsa (0:00 da turgan pleer birinchi pufakchani bo'yamasin).
  const activeKey = usePlayback((p) =>
    p.key === meeting.id && p.started && bubbles.length ? (bubbles[bubbleIndexAt(bubbles, p.t)]?.key ?? null) : null,
  );
  const label = (id: string | null) => (id ? speakerLabel(id, speakers, uiLang) : t('tr.unknown'));

  useEffect(() => {
    if (!focus || !bubbles.length || query.trim()) return;
    const idx = bubbleIndexAt(bubbles, focus.t);
    try {
      listRef.current?.scrollToIndex({ index: idx, animated: true, viewPosition: 0.2 });
    } catch {
      /* hali o'lchanmagan - onScrollToIndexFailed hal qiladi */
    }
  }, [focus, bubbles, query]);

  if (!meeting.transcript.available) return <Banner tone="info" text={t('tr.notReady')} />;
  if (q.isLoading) return <Loading />;
  if (q.error) {
    const e = q.error;
    return <Banner tone="bad" text={e instanceof ApiError && e.code === 'not_ready' ? t('tr.notReady') : t('common.error')} />;
  }
  if (!tr) return null;

  const share = async (format: 'txt' | 'srt') => {
    let text: string;
    try {
      text = await meetings.exportTranscript(meeting.id, { format, speakers: true, timestamps: true });
    } catch (e) {
      showToast(errorText(t, e));
      return;
    }
    try {
      // Uzun transkript Binder chegarasidan oshmasin (TransactionTooLargeException).
      await Share.share({ message: shareableText(text, t).text, title: meeting.title });
    } catch (e) {
      showToast(errorText(t, e));
    }
  };

  const speakerActions = (sp: Speaker): PickerOption<SpeakerAction>[] => {
    const opts: PickerOption<SpeakerAction>[] = [{ value: 'rename', label: t('tr.rename') }];
    if (sp.suggestedName && !sp.name) opts.unshift({ value: 'accept', label: t('sum.suggested', { name: sp.suggestedName }) });
    if (visibleSpeakers(speakers).length > 1) opts.push({ value: 'merge', label: t('tr.merge') });
    return opts;
  };

  const header = (
    <View>
      {tr.engine === 'router' ? <Banner tone="info" text={t('detail.routerMode')} /> : null}
      {(meeting.expectedSpeakers ?? 0) > 4 ? <Banner tone="warn" text={t('detail.speakersOver4')} /> : null}
      <View style={[ui.wrap, { marginBottom: 8 }]}>
        {visibleSpeakers(speakers).map((sp) => (
          <SpeakerChip key={sp.id} speaker={sp} label={label(sp.id)} onPress={() => setSpeakerMenu(sp)} />
        ))}
      </View>
      <Field testID="transcript-search" placeholder={t('tr.search')} value={query} onChangeText={setQuery} />
      <View style={[ui.row, { marginBottom: 8 }]}>
        <Button small variant="secondary" title={t('tr.shareTxt')} onPress={() => share('txt')} />
        <Button small variant="secondary" title={t('tr.shareSrt')} onPress={() => share('srt')} style={{ marginLeft: 8 }} />
      </View>
      {query.trim() && !matches.length ? <Muted>{t('tr.noResults')}</Muted> : null}
    </View>
  );

  return (
    <View style={{ flex: 1 }}>
      <FlatList
        ref={listRef}
        testID="transcript-list"
        data={shown}
        keyExtractor={(b) => b.key}
        extraData={activeKey}
        ListHeaderComponent={header}
        initialNumToRender={30}
        windowSize={11}
        onScrollToIndexFailed={(info) => {
          setTimeout(() => listRef.current?.scrollToIndex({ index: info.index, animated: true }), 250);
        }}
        renderItem={({ item }) => (
          <BubbleRow
            bubble={item}
            label={label(item.speaker)}
            editedLabel={t('tr.edited')}
            active={item.key === activeKey}
            onPress={() => onSeek?.(item.start)}
            onLongPress={() => setEditBubble(item)}
          />
        )}
      />

      <PickerModal
        visible={!!speakerMenu}
        title={speakerMenu ? label(speakerMenu.id) : ''}
        options={speakerMenu ? speakerActions(speakerMenu) : []}
        onCancel={() => setSpeakerMenu(null)}
        onPick={(a) => {
          const sp = speakerMenu;
          setSpeakerMenu(null);
          if (!sp) return;
          if (a === 'rename') setRenaming(sp);
          if (a === 'merge') setMerging(sp);
          if (a === 'accept' && sp.suggestedName) muts.renameSpeaker.mutate({ speakerId: sp.id, name: sp.suggestedName });
        }}
      />
      <PromptModal
        visible={!!renaming}
        title={t('tr.rename')}
        initial={renaming?.name ?? renaming?.suggestedName ?? ''}
        placeholder={t('tr.renamePlaceholder')}
        maxLength={60}
        allowEmpty
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => {
          if (renaming) muts.renameSpeaker.mutate({ speakerId: renaming.id, name: name || null });
          setRenaming(null);
        }}
      />
      <PickerModal
        visible={!!merging}
        title={merging ? t('tr.mergeInto', { from: label(merging.id) }) : ''}
        options={visibleSpeakers(speakers)
          .filter((sp) => sp.id !== merging?.id)
          .map((sp) => ({ value: sp.id, label: label(sp.id) }))}
        onCancel={() => setMerging(null)}
        onPick={(into) => {
          if (merging) muts.mergeSpeakers.mutate({ from: [merging.id], into });
          setMerging(null);
        }}
      />
      <PickerModal
        visible={!!editBubble}
        title={editBubble ? `${label(editBubble.speaker)} · ${formatClock(editBubble.start)}` : ''}
        options={(editBubble?.segments ?? []).flatMap((seg): PickerOption<SegmentEdit>[] => [
          { value: { kind: 'text', seg }, label: `${t('tr.editText')}: ${seg.text.slice(0, 60)}${seg.text.length > 60 ? '…' : ''}`, hint: formatClock(seg.start) },
          ...(tr.speakersAvailable ? [{ value: { kind: 'speaker', seg } as SegmentEdit, label: `${t('tr.changeSpeaker')} (${formatClock(seg.start)})` }] : []),
        ])}
        onCancel={() => setEditBubble(null)}
        onPick={(v) => {
          setEditBubble(null);
          if (v.kind === 'text') setEditSegment(v.seg);
          else setRespeaker(v.seg);
        }}
      />
      <PromptModal
        visible={!!editSegment}
        title={t('tr.editText')}
        initial={editSegment?.text ?? ''}
        multiline
        maxLength={2000}
        onCancel={() => setEditSegment(null)}
        onSubmit={(text) => {
          if (editSegment && text !== editSegment.text) muts.patchSegment.mutate({ segmentId: editSegment.id, body: { text } });
          setEditSegment(null);
        }}
      />
      <PickerModal
        visible={!!respeaker}
        title={t('tr.changeSpeaker')}
        options={visibleSpeakers(speakers).map((sp) => ({ value: sp.id, label: label(sp.id) }))}
        onCancel={() => setRespeaker(null)}
        onPick={(speaker) => {
          if (respeaker && speaker !== respeaker.speaker) muts.patchSegment.mutate({ segmentId: respeaker.id, body: { speaker } });
          setRespeaker(null);
        }}
      />
    </View>
  );
}

function SpeakerChip({ speaker, label, onPress }: { speaker: Speaker; label: string; onPress: () => void }) {
  const th = useTheme();
  const color = speakerColor(speaker.id);
  return (
    <Pressable
      testID={`speaker-${speaker.id}`}
      accessibilityRole="button"
      onPress={onPress}
      style={[s.speakerChip, { borderColor: color, backgroundColor: th.surface }]}>
      <View style={[s.dot, { backgroundColor: color }]} />
      <Text style={{ color: th.text, fontWeight: '600' }}>{label}</Text>
      {speaker.suggestedName && !speaker.name ? <Text style={{ color: th.textMuted }}> ?</Text> : null}
    </Pressable>
  );
}

export function BubbleRow({
  bubble,
  label,
  editedLabel,
  active,
  onPress,
  onLongPress,
}: {
  bubble: Bubble;
  label: string;
  editedLabel: string;
  /** Hozir eshitilayotgan pufakcha. */
  active?: boolean;
  onPress?: () => void;
  onLongPress?: () => void;
}) {
  const th = useTheme();
  const color = speakerColor(bubble.speaker);
  const info = th.tones.info.fg;
  return (
    <Pressable
      testID={`bubble-${bubble.key}`}
      accessibilityState={active ? { selected: true } : undefined}
      onPress={onPress}
      onLongPress={onLongPress}
      style={s.bubbleWrap}>
      <View style={[s.bubble, { backgroundColor: active ? th.brandSoft : th.surface, borderLeftColor: color }]}>
        <View style={[ui.row, { marginBottom: 2 }]}>
          <Text style={[s.name, { color }]}>{label}</Text>
          <View style={s.timeChip}>
            <Play size={12} color={info} fill={info} strokeWidth={2} />
            <Text style={[s.time, { color: info }]}>{formatClock(bubble.start)}</Text>
          </View>
          {bubble.edited ? <Text style={[s.time, { color: th.textMuted }]}> · {editedLabel}</Text> : null}
        </View>
        <Text selectable style={[s.text, { color: th.text }]}>
          {bubble.text}
        </Text>
      </View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  speakerChip: { flexDirection: 'row', alignItems: 'center', borderWidth: 1.5, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, marginRight: 6, marginBottom: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  bubbleWrap: { marginBottom: 8 },
  bubble: { borderRadius: 12, padding: 10, borderLeftWidth: 4 },
  name: { fontWeight: '700', fontSize: 13, marginRight: 8 },
  time: { fontSize: 12, fontVariant: ['tabular-nums'] },
  timeChip: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  text: { fontSize: 15, lineHeight: 21 },
});

