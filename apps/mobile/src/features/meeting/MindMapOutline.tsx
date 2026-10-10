/**
 * Xaritaning "Ro'yxat" ko'rinishi: o'sha daraxt, chekinish bilan. Tor ekranda
 * o'qish oson va TalkBack har bir bo'lakka to'xtaydi (SVG'da bunday emas).
 * Yig'ilgan shoxlar va tanlangan tugun xarita bilan UMUMIY (bir holat).
 */
import { ChevronDown, ChevronRight } from 'lucide-react-native';
import { useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { useTheme } from '@/ui/theme';
import { hit, iconSize, stroke, type as typeScale } from '@/ui/tokens';

import { formatClock } from './formatDate';
import { metaLineOf, outlineRows, pressAction, type MindNode } from './mindmapModel';

export interface MindMapOutlineProps {
  root: MindNode;
  collapsed: ReadonlySet<string>;
  selectedId: string | null;
  onPress: (n: MindNode) => void;
  onToggle: (id: string) => void;
}

/** Har chuqurlik pog'onasi uchun chekinish (dp). */
const INDENT = 20;

export function MindMapOutline({ root, collapsed, selectedId, onPress, onToggle }: MindMapOutlineProps) {
  const th = useTheme();
  const t = useT();
  const rows = useMemo(() => outlineRows(root, collapsed), [root, collapsed]);
  return (
    <ScrollView testID="mindmap-outline" style={s.flex} contentContainerStyle={s.content}>
      <Text accessibilityRole="header" style={[typeScale.headline, s.title, { color: th.text }]}>
        {root.label}
      </Text>
      {rows.map(({ node: n, depth, collapsed: isCollapsed }) => {
        const fg = th.tones[n.tone].fg;
        const hasKids = n.children.length > 0;
        const meta = metaLineOf(n);
        const selected = n.id === selectedId;
        const Chevron = isCollapsed ? ChevronRight : ChevronDown;
        // Yorliq bosish natijasini aytadi - xaritadagi bilan bir xil qoida (`pressAction`).
        const action = pressAction(n, n.children.length);
        const label =
          action === 'toggle'
            ? t(isCollapsed ? 'recs.map.expandNode' : 'recs.map.collapseNode', { name: n.label })
            : action === 'seek' && n.start != null
              ? t('recs.map.playAt', { name: n.label, time: formatClock(n.start) })
              : n.label;
        return (
          <View key={n.id} style={[s.row, { paddingLeft: (depth - 1) * INDENT }]}>
            {hasKids ? (
              <Pressable
                testID={`mm-row-toggle-${n.id}`}
                accessibilityRole="button"
                accessibilityLabel={t(isCollapsed ? 'recs.map.expandNode' : 'recs.map.collapseNode', { name: n.label })}
                accessibilityState={{ expanded: !isCollapsed }}
                onPress={() => onToggle(n.id)}
                style={s.lead}>
                <Chevron size={iconSize.sm} color={fg} strokeWidth={stroke.small} />
              </Pressable>
            ) : (
              <View style={s.lead}>
                <View style={[s.dot, { backgroundColor: fg }]} />
              </View>
            )}
            <Pressable
              testID={`mm-row-${n.id}`}
              accessibilityRole="button"
              accessibilityLabel={label}
              accessibilityState={action === 'toggle' ? { selected, expanded: !isCollapsed } : { selected }}
              disabled={action == null}
              onPress={() => onPress(n)}
              style={({ pressed }) => [s.body, (selected || pressed) && { backgroundColor: th.surfaceAlt }]}>
              <Text style={[depth === 1 ? s.branch : typeScale.sub, { color: depth === 1 ? fg : th.text }]}>{n.label}</Text>
              {meta ? <Text style={[typeScale.caption, { color: th.textMuted }]}>{meta}</Text> : null}
            </Pressable>
          </View>
        );
      })}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  flex: { flex: 1 },
  content: { paddingHorizontal: 12, paddingTop: 4, paddingBottom: 32 },
  title: { marginBottom: 8, marginLeft: 4 },
  row: { flexDirection: 'row', alignItems: 'flex-start' },
  lead: { width: 32, minHeight: hit.min, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 6, height: 6, borderRadius: 3 },
  body: { flex: 1, minHeight: hit.min, justifyContent: 'center', paddingVertical: 8, paddingHorizontal: 8, borderRadius: 10, gap: 2 },
  branch: { fontSize: 15, lineHeight: 20, fontWeight: '600' },
});
