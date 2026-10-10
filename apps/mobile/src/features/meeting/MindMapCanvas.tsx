/**
 * Xaritaning SVG chizmasi: `layoutMindMap` natijasi - bog'lovchi egri chiziqlar,
 * tugunlar va yig'ish tugmalari. Ikki tomonga aylantiriladi (tashqi vertikal,
 * ichki gorizontal ScrollView), kattalik `scale` bilan (viewBox o'zgarmaydi -
 * matn tiniq qoladi).
 *
 * NIMA UCHUN SVG, View emas: egri bog'lovchilar va yuzlab tugunni native ko'rinishda
 * chizish arzon; tugun matnini o'rash `mindmapModel.wrapText` da (SVG matnni o'zi o'ramaydi).
 *
 * NIMA UCHUN PLITKALAR (bitta katta <Svg> emas): react-native-svg Android'da butun
 * ko'rinish o'lchamida BITTA bitmap ajratadi. 10 mavzuli yig'ilish xaritasi 100% da ~120 MB,
 * 30 mavzulisi 180% da ~1 GB bo'lardi - Android 100 MB dan katta bitmap'ni chizmaydi va
 * ilova yiqiladi. Endi xarita 1024 px li plitkalarga bo'linadi (har biri <= 4 MB) va faqat
 * ekran atrofidagilari chiziladi - xotira xarita o'lchamiga emas, ekran o'lchamiga bog'liq.
 *
 * TalkBack SVG ichidagi bo'laklarga to'xtamaydi - shu uchun "Ro'yxat" ko'rinishi bor
 * (MindMapOutline); bu yerda har tugunga baribir nom beriladi.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  PixelRatio,
  ScrollView,
  StyleSheet,
  useWindowDimensions,
  View,
  type LayoutChangeEvent,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import Svg, { Circle, G, Path, Rect, Text as SvgText } from 'react-native-svg';

import { useT } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { useTheme, type Theme } from '@/ui/theme';

import { formatClock } from './formatDate';
import {
  BAR_INSET,
  canvasTiles,
  KNOB_HIT,
  MIND_METRICS,
  pressAction,
  tileContent,
  visibleTiles,
  type CanvasTile,
  type LaidNode,
  type MindLayout,
  type Viewport,
} from './mindmapModel';

export interface MindMapCanvasProps {
  layout: MindLayout;
  scale: number;
  selectedId: string | null;
  onNodePress: (n: LaidNode) => void;
  onToggle: (id: string) => void;
  /**
   * Oxirgi yig'ilgan/ochilgan tugun: xarita qayta joylashganda u ekranda O'Z JOYIDA qoladi
   * (aks holda ildiz markazga surilib, bosilgan shox ko'zdan qochardi).
   */
  anchor?: { id: string; n: number } | null;
}

const m = MIND_METRICS;

function nodeColors(th: Theme, n: LaidNode, selected: boolean) {
  const tone = th.tones[n.tone];
  if (n.depth === 0) return { fill: th.primary, stroke: selected ? th.brand : th.primary, text: th.primaryText, meta: th.primaryText, bar: null };
  if (n.depth === 1) return { fill: tone.bg, stroke: selected ? th.brand : tone.fg, text: tone.fg, meta: tone.fg, bar: null };
  return { fill: th.surface, stroke: selected ? th.brand : th.border, text: th.text, meta: th.textMuted, bar: tone.fg };
}

/** Ekran o'quvchi yorlig'i bosish natijasini aytadi (ochish/yig'ish yoki o'sha joydan eshitish). */
function nodeLabel(t: TFn, n: LaidNode): string {
  const action = pressAction(n, n.childCount);
  if (action === 'toggle') return t(n.collapsed ? 'recs.map.expandNode' : 'recs.map.collapseNode', { name: n.label });
  if (action === 'seek' && n.start != null) return t('recs.map.playAt', { name: n.label, time: formatClock(n.start) });
  return n.label;
}

/** Bir xil plitkalar (OBYEKT bo'yicha: xarita qayta joylashsa kalit o'sha, o'lcham boshqa). */
const sameTiles = (a: CanvasTile[], b: CanvasTile[]) => a.length === b.length && a.every((x, i) => x === b[i]);

export const MindMapCanvas = memo(function MindMapCanvas({ layout, scale, selectedId, onNodePress, onToggle, anchor }: MindMapCanvasProps) {
  const win = useWindowDimensions();
  const pixelRatio = PixelRatio.get();
  const tiles = useMemo(() => canvasTiles(layout, scale, pixelRatio), [layout, scale, pixelRatio]);

  const vRef = useRef<ScrollView>(null);
  const hRef = useRef<ScrollView>(null);
  const offset = useRef({ x: 0, y: 0 });
  // Native o'lcham hali kelmagan bo'lsa (birinchi kadr, testlar) - ekran o'lchami.
  const size = useRef({ w: 0, h: 0 });
  const viewOf = useCallback(
    (): Viewport => ({ x: offset.current.x, y: offset.current.y, w: size.current.w || win.width, h: size.current.h || win.height }),
    [win.width, win.height],
  );

  // Chiziladigan plitkalar: aylantirishda faqat to'plam O'ZGARGANDA qayta chiziladi.
  const [mounted, setMounted] = useState<CanvasTile[]>(() => visibleTiles(tiles, scale, viewOf()));
  const refresh = useCallback(() => {
    const next = visibleTiles(tiles, scale, viewOf());
    setMounted((prev) => (sameTiles(prev, next) ? prev : next));
  }, [tiles, scale, viewOf]);
  useEffect(() => refresh(), [refresh]);

  const scrollToY = useCallback(
    (y: number) => {
      const max = Math.max(0, layout.height * scale - (size.current.h || win.height));
      const target = Math.min(max, Math.max(0, y));
      offset.current.y = target;
      vRef.current?.scrollTo?.({ y: target, animated: false });
      refresh();
    },
    [layout.height, scale, win.height, refresh],
  );

  // Birinchi ochilishda ildiz ekran o'rtasida: ildiz butun daraxt balandligining o'rtasida
  // turadi - aks holda katta xaritaning birinchi ekrani bo'sh ko'rinardi.
  const centered = useRef(false);
  const center = useCallback(() => {
    if (centered.current || !size.current.h) return;
    const root = layout.nodes.find((n) => n.depth === 0);
    if (!root) return;
    centered.current = true;
    scrollToY((root.y + root.h / 2) * scale - size.current.h / 2);
  }, [layout.nodes, scale, scrollToY]);

  // Kattalik o'zgarsa - ekran markazidagi joy markazda qoladi.
  const prevScale = useRef(scale);
  useEffect(() => {
    const k = scale / prevScale.current;
    prevScale.current = scale;
    if (k === 1) return;
    const { w, h } = viewOf();
    const x = Math.max(0, (offset.current.x + w / 2) * k - w / 2);
    offset.current.x = x;
    hRef.current?.scrollTo?.({ x, animated: false });
    scrollToY((offset.current.y + h / 2) * k - h / 2);
  }, [scale, viewOf, scrollToY]);

  // Shox yig'ilsa/ochilsa - bosilgan tugun ekrandagi joyida qoladi.
  const prevLayout = useRef(layout);
  useEffect(() => {
    const before = prevLayout.current;
    prevLayout.current = layout;
    if (!anchor || before === layout) return;
    const a = before.nodes.find((n) => n.id === anchor.id);
    const b = layout.nodes.find((n) => n.id === anchor.id);
    if (a && b && a.y !== b.y) scrollToY(offset.current.y + (b.y - a.y) * scale);
  }, [layout, anchor, scale, scrollToY]);

  const onVLayout = (e: LayoutChangeEvent) => {
    size.current = { w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height };
    center();
    refresh();
  };
  const onV = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    offset.current.y = e.nativeEvent.contentOffset.y;
    refresh();
  };
  const onH = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    offset.current.x = e.nativeEvent.contentOffset.x;
    refresh();
  };

  return (
    <ScrollView
      ref={vRef}
      testID="mindmap-canvas"
      style={s.flex}
      contentContainerStyle={s.vContent}
      onLayout={onVLayout}
      onContentSizeChange={center}
      onScroll={onV}
      scrollEventThrottle={48}>
      <ScrollView ref={hRef} horizontal contentContainerStyle={s.hContent} showsHorizontalScrollIndicator onScroll={onH} scrollEventThrottle={48}>
        <View style={{ width: layout.width * scale, height: layout.height * scale }}>
          {mounted.map((tile) => (
            <MindTile key={tile.key} tile={tile} layout={layout} scale={scale} selectedId={selectedId} onNodePress={onNodePress} onToggle={onToggle} />
          ))}
        </View>
      </ScrollView>
    </ScrollView>
  );
});

/** Bitta plitka: o'z bo'lagini `viewBox` bilan kesib chizadi (chetdagi tugun qo'shni plitkada davom etadi). */
const MindTile = memo(function MindTile({
  tile,
  layout,
  scale,
  selectedId,
  onNodePress,
  onToggle,
}: {
  tile: CanvasTile;
  layout: MindLayout;
  scale: number;
  selectedId: string | null;
  onNodePress: (n: LaidNode) => void;
  onToggle: (id: string) => void;
}) {
  const th = useTheme();
  const t = useT();
  const content = useMemo(() => tileContent(layout, tile), [layout, tile]);
  return (
    <Svg
      style={{ position: 'absolute', left: tile.x * scale, top: tile.y * scale }}
      width={tile.w * scale}
      height={tile.h * scale}
      viewBox={`${tile.x} ${tile.y} ${tile.w} ${tile.h}`}>
      {content.edges.map((e) => (
        <Path key={e.id} d={e.d} stroke={th.tones[e.tone].fg} strokeOpacity={0.55} strokeWidth={1.6} fill="none" />
      ))}
      {content.nodes.map(({ node: n, home }) => {
        const selected = n.id === selectedId;
        const c = nodeColors(th, n, selected);
        const weight = n.depth === 0 ? '700' : n.depth === 1 ? '600' : '400';
        return (
          <G
            key={n.id}
            testID={home ? `mm-node-${n.id}` : undefined}
            accessible={home}
            accessibilityLabel={home ? nodeLabel(t, n) : undefined}
            onPress={() => onNodePress(n)}>
            <Rect
              x={n.x}
              y={n.y}
              width={n.w}
              height={n.h}
              rx={n.depth === 0 ? 14 : 10}
              fill={c.fill}
              stroke={c.stroke}
              strokeOpacity={selected || n.depth !== 1 ? 1 : 0.35}
              strokeWidth={selected ? 2 : 1}
            />
            {c.bar ? <Rect x={n.x + 5} y={n.y + 8} width={3} height={Math.max(4, n.h - 16)} rx={1.5} fill={c.bar} /> : null}
            {n.lines.map((line, i) => (
              <SvgText
                key={i}
                x={n.x + m.padX + (c.bar ? BAR_INSET : 0)}
                y={n.y + m.padY + i * n.lineH + n.lineH * 0.74}
                fontSize={n.fontSize}
                fontWeight={weight}
                fill={c.text}>
                {line}
              </SvgText>
            ))}
            {n.metaLines.map((line, i) => (
              <SvgText
                key={`m${i}`}
                x={n.x + m.padX + (c.bar ? BAR_INSET : 0)}
                y={n.y + m.padY + n.lines.length * n.lineH + i * m.metaLineH + m.metaLineH * 0.74}
                fontSize={m.metaSize}
                fill={c.meta}
                fillOpacity={n.depth === 2 ? 1 : 0.8}>
                {line}
              </SvgText>
            ))}
          </G>
        );
      })}
      {content.knobs.map(({ node: n, home }) => {
        const cx = n.x + n.w;
        const cy = n.y + n.h / 2;
        const fg = th.tones[n.tone].fg;
        return (
          <G
            key={`k-${n.id}`}
            testID={home ? `mm-toggle-${n.id}` : undefined}
            accessible={home}
            accessibilityLabel={home ? t(n.collapsed ? 'recs.map.expandNode' : 'recs.map.collapseNode', { name: n.label }) : undefined}
            onPress={() => onToggle(n.id)}>
            {/* Ko'rinmas katta doira - barmoq uchun nishon (~36 dp), ko'rinadigani kichik. */}
            <Circle cx={cx} cy={cy} r={KNOB_HIT} fill={th.bg} fillOpacity={0.01} />
            <Circle cx={cx} cy={cy} r={m.knob} fill={th.bg} stroke={fg} strokeWidth={1.5} />
            <Path d={`M${cx - 4} ${cy} H${cx + 4}${n.collapsed ? ` M${cx} ${cy - 4} V${cy + 4}` : ''}`} stroke={fg} strokeWidth={1.6} strokeLinecap="round" />
            {n.collapsed ? (
              <SvgText x={cx + m.knob + 4} y={cy + 4} fontSize={11} fontWeight="600" fill={fg}>
                {String(n.childCount)}
              </SvgText>
            ) : null}
          </G>
        );
      })}
    </Svg>
  );
});

const s = StyleSheet.create({
  flex: { flex: 1 },
  // Pastki o'ng burchakdagi kattalik tugmalari oxirgi tugunni yopmasin.
  vContent: { paddingBottom: 72 },
  hContent: { paddingRight: 16 },
});
