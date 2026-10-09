/**
 * `markdownLite` bloklarini chizish: sarlavha, ro'yxat, paragraf; qalin/kursiv/kod -
 * ichki `Text`. Matn tanlanadi (nusxalash uchun). Ko'rsatish qoidalari - `lib/markdownLite.ts`.
 */
import { useMemo } from 'react';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { parseMarkdownLite, type Inline } from '@/lib/markdownLite';

import { useTheme } from './theme';

function Inlines({ parts, codeBg }: { parts: Inline[]; codeBg: string }) {
  return (
    <>
      {parts.map((p, i) =>
        !p.bold && !p.italic && !p.code ? (
          p.text
        ) : (
          <Text
            key={i}
            style={[p.bold && s.bold, p.italic && s.italic, p.code && [s.code, { backgroundColor: codeBg }]]}>
            {p.text}
          </Text>
        ),
      )}
    </>
  );
}

export function MarkdownLite({ text, testID, style }: { text: string; testID?: string; style?: StyleProp<ViewStyle> }) {
  const th = useTheme();
  const blocks = useMemo(() => parseMarkdownLite(text), [text]);
  return (
    <View testID={testID} style={style}>
      {blocks.map((b, i) => {
        if (b.kind === 'heading') {
          return (
            <Text key={i} selectable style={[s.heading, { color: th.text }]}>
              <Inlines parts={b.inlines} codeBg={th.surfaceAlt} />
            </Text>
          );
        }
        if (b.kind === 'bullet') {
          return (
            <View key={i} style={[s.bulletRow, { paddingLeft: b.depth * 14 }]}>
              <Text style={[s.marker, { color: th.textMuted }]}>{b.marker}</Text>
              <Text selectable style={[s.text, s.bulletText, { color: th.text }]}>
                <Inlines parts={b.inlines} codeBg={th.surfaceAlt} />
              </Text>
            </View>
          );
        }
        return (
          <Text key={i} selectable style={[s.text, s.para, { color: th.text }]}>
            <Inlines parts={b.inlines} codeBg={th.surfaceAlt} />
          </Text>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  text: { fontSize: 15, lineHeight: 22 },
  para: { marginBottom: 6 },
  heading: { fontSize: 15, lineHeight: 21, fontWeight: '700', marginTop: 4, marginBottom: 4 },
  bulletRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 3 },
  marker: { width: 22, fontSize: 15, lineHeight: 22 },
  bulletText: { flex: 1 },
  bold: { fontWeight: '700' },
  italic: { fontStyle: 'italic' },
  code: { fontFamily: 'monospace', fontSize: 13, borderRadius: 4 },
});
