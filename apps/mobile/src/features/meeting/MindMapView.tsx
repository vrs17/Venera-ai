/**
 * Xulosa tabidagi "Xarita" ko'rinishi (Plaud kabi aqliy xarita): xulosa daraxt ko'rinishida -
 * ildiz sarlavha, shoxlar mavzular, qarorlar, vazifalar (mas'ul bilan) va ochiq savollar.
 *
 * Boshqaruv:
 *  - xarita YIG'IQ ochiladi (ildiz va shoxlar, yonida bandlar soni): telefon ekraniga sig'adi,
 *    odam kerakli shoxni ochadi; ildiz ekran o'rtasida, kattalik - shoxlar ekran eniga sig'adigan;
 *  - shox (mavzu yoki guruh) bosilsa - ochiladi/yig'iladi, band bosilsa - pleer va transkript
 *    o'sha joyga o'tadi (xulosa dalil chiplari bilan BIR XIL yo'l, `onSeek`);
 *  - [-] 100% [+] - kattalik (pinch uchun gesture-handler qo'shilmaydi, spec 0);
 *  - ro'yxat belgisi - tor ekran va TalkBack uchun shu daraxt chekinish bilan.
 */
import { ChevronsDownUp, ChevronsUpDown, ListTree, Network, ZoomIn, ZoomOut } from 'lucide-react-native';
import { useCallback, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import type { Meeting } from '@/api/types';
import { useT } from '@/features/settings/settingsStore';
import { Banner, Loading } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { IconButton } from '@/ui/IconButton';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

import { MindMapCanvas } from './MindMapCanvas';
import { buildMindMap, collapsibleIds, fitZoom, layoutMindMap, pressAction, ZOOM_STEPS, type LaidNode, type MindNode } from './mindmapModel';
import { MindMapOutline } from './MindMapOutline';
import { useActionItems, useSummaries, useSummary } from './queries';

export { ZOOM_STEPS } from './mindmapModel';
/** Bundan tor ekranda boshidan "Ro'yxat" - xaritaning bir ustuni ham sig'maydi. */
const NARROW_DP = 340;
/** Xarita chetlaridagi bo'sh joy (ScrollView paddingRight) - sig'ishni hisoblashda. */
const EDGE_DP = 16;

type Mode = 'map' | 'outline';

export interface MindMapViewProps {
  root: MindNode;
  onSeek?: (sec: number) => void;
}

export function MindMapView({ root, onSeek }: MindMapViewProps) {
  const t = useT();
  const th = useTheme();
  const { width } = useWindowDimensions();
  const [mode, setMode] = useState<Mode>(() => (width > 0 && width < NARROW_DP ? 'outline' : 'map'));
  const foldable = useMemo(() => collapsibleIds(root), [root]);
  // Yig'iq boshlanadi: katta yig'ilishda ham birinchi ekran - ildiz va shoxlar.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set(foldable));
  const [fitted] = useState(() => fitZoom(layoutMindMap(root, new Set(foldable)).width + EDGE_DP, width));
  const [zoom, setZoom] = useState(fitted);
  const [selected, setSelected] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<{ id: string; n: number } | null>(null);

  const layout = useMemo(() => layoutMindMap(root, collapsed), [root, collapsed]);
  const anyCollapsed = foldable.some((id) => collapsed.has(id));

  const toggle = useCallback((id: string) => {
    setAnchor((a) => ({ id, n: (a?.n ?? 0) + 1 }));
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const press = useCallback(
    (n: LaidNode | MindNode) => {
      const kids = 'childCount' in n ? n.childCount : n.children.length;
      const action = pressAction(n, kids);
      if (action === 'toggle') toggle(n.id);
      else if (action === 'seek' && n.start != null) {
        setSelected(n.id);
        onSeek?.(n.start);
      }
    },
    [onSeek, toggle],
  );

  return (
    <View style={s.flex} testID="mindmap">
      <View style={s.toolbar}>
        <Text style={[typeScale.caption, s.hint, { color: th.textMuted }]}>{t('recs.map.hint')}</Text>
        <IconButton
          testID={mode === 'map' ? 'mindmap-mode-outline' : 'mindmap-mode-map'}
          icon={mode === 'map' ? ListTree : Network}
          label={mode === 'map' ? t('recs.map.modeOutline') : t('recs.map.modeMap')}
          onPress={() => setMode(mode === 'map' ? 'outline' : 'map')}
        />
        <IconButton
          testID="mindmap-fold"
          icon={anyCollapsed ? ChevronsUpDown : ChevronsDownUp}
          label={anyCollapsed ? t('recs.map.expandAll') : t('recs.map.collapseAll')}
          disabled={!foldable.length}
          onPress={() => {
            setAnchor(null);
            setCollapsed(anyCollapsed ? new Set() : new Set(foldable));
          }}
        />
      </View>

      {mode === 'map' ? (
        <View style={s.flex}>
          <MindMapCanvas layout={layout} scale={ZOOM_STEPS[zoom]} selectedId={selected} onNodePress={press} onToggle={toggle} anchor={anchor} />
          <View style={[s.zoom, { backgroundColor: th.surface, borderColor: th.border }]}>
            <IconButton
              testID="mindmap-zoom-out"
              icon={ZoomOut}
              size={20}
              label={t('recs.map.zoomOut')}
              disabled={zoom === 0}
              onPress={() => setZoom((z) => Math.max(0, z - 1))}
            />
            <Pressable
              testID="mindmap-zoom-reset"
              accessibilityRole="button"
              accessibilityLabel={t('recs.map.zoomReset')}
              onPress={() => setZoom(fitted)}
              style={s.zoomLabel}>
              <Text style={[typeScale.micro, s.tabular, { color: th.textSoft }]}>{`${Math.round(ZOOM_STEPS[zoom] * 100)}%`}</Text>
            </Pressable>
            <IconButton
              testID="mindmap-zoom-in"
              icon={ZoomIn}
              size={20}
              label={t('recs.map.zoomIn')}
              disabled={zoom === ZOOM_STEPS.length - 1}
              onPress={() => setZoom((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))}
            />
          </View>
        </View>
      ) : (
        <MindMapOutline root={root} collapsed={collapsed} selectedId={selected} onPress={press} onToggle={toggle} />
      )}
    </View>
  );
}

/**
 * Xarita mazmuni: Xulosa tabida tanlangan (yoki asosiy) xulosani yuklab xaritaga aylantiradi.
 * So'rovlar xulosa ko'rinishi bilan umumiy kesh kalitida - qayta yuklanmaydi.
 */
export function MindMapTab({ meeting, summaryId, onSeek }: { meeting: Meeting; summaryId?: string | null; onSeek?: (sec: number) => void }) {
  const t = useT();
  const transcriptReady = meeting.transcript.available;
  const summaries = useSummaries(meeting.id, transcriptReady, meeting.status === 'summarizing');
  const items = useMemo(() => summaries.data?.items ?? [], [summaries.data]);
  const activeId = summaryId && items.some((x) => x.id === summaryId) ? summaryId : (meeting.primarySummaryId ?? items[0]?.id ?? null);
  const card = items.find((x) => x.id === activeId) ?? null;
  const q = useSummary(meeting.id, activeId);
  const content = q.data?.content ?? null;
  // Asosiy xulosada vazifalar jonli ro'yxatdan (Vazifalar tabi bilan umumiy kesh).
  const primary = !!card?.primary;
  const live = useActionItems(meeting.id, primary);
  const actions = primary ? (live.data?.items ?? null) : null;
  const summarySpeakers = q.data?.speakers;
  const root = useMemo(
    () => buildMindMap(content, { meeting, speakers: meeting.speakers.length ? meeting.speakers : (summarySpeakers ?? []), actions }),
    [content, meeting, summarySpeakers, actions],
  );

  // Eski mazmun bo'lsa (qayta yaratilmoqda) - xarita ko'rinib turadi. Boshqa xulosaga
  // o'tilsa (`key`) - yig'ish/kattalik holati yangidan (eski shox id'lari boshqa daraxtniki).
  if (root) return <MindMapView key={activeId ?? 'none'} root={root} onSeek={onSeek} />;
  if (!transcriptReady) {
    const failed = meeting.status === 'failed';
    return (
      <View style={s.pad}>
        <Banner tone={failed ? 'bad' : 'info'} text={failed ? (meeting.error?.message ?? t('common.error')) : t('detail.processing')} />
      </View>
    );
  }
  if (summaries.isLoading || (activeId != null && q.isLoading)) return <Loading />;
  const busy = card?.status === 'queued' || card?.status === 'running' || meeting.summaryStatus === 'queued' || meeting.summaryStatus === 'running';
  if (busy) {
    return (
      <View style={s.pad}>
        <Banner tone="info" text={t('detail.processing')} />
      </View>
    );
  }
  return <EmptyState compact testID="mindmap-empty" icon={Network} title={t('recs.map.empty')} />;
}

const s = StyleSheet.create({
  flex: { flex: 1 },
  pad: { padding: 12 },
  toolbar: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingLeft: 16, paddingRight: 8, paddingTop: 4 },
  hint: { flex: 1 },
  zoom: {
    position: 'absolute',
    right: 12,
    bottom: 12,
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 2,
    elevation: 3,
  },
  zoomLabel: { minWidth: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  tabular: { fontVariant: ['tabular-nums'] },
});
