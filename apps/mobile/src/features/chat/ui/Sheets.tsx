/**
 * Chat oynasi: javob manbalari ro'yxati (Mini App `SourcesSheet` kabi) - pastdan
 * chiqadigan varaq; orqaga tugmasi yopadi.
 *
 * Suhbatlar tarixi endi bu yerda emas - chap panelda (`features/nav/AppDrawer`, `ChatList`).
 */
import { BookOpen, Database, Landmark, X } from 'lucide-react-native';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Linking, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { AnswerSource, ChatApi } from '@/api/chat';
import { useT } from '@/features/settings/settingsStore';
import { errorText, showToast } from '@/ui/errors';
import { useTheme, type Theme } from '@/ui/theme';

function Sheet({ visible, onClose, title, children }: { visible: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  const th = useTheme();
  const t = useT();
  const insets = useSafeAreaInsets();
  const s = useMemo(() => makeStyles(th), [th]);
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={s.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel={t('common.close')} />
        <View style={[s.sheet, { paddingBottom: Math.max(insets.bottom, 12) }]}>
          <View style={s.grabber} />
          <View style={s.head}>
            <Text style={s.title} accessibilityRole="header">
              {title}
            </Text>
            <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel={t('common.close')} style={s.close}>
              <X size={18} color={th.textSoft} strokeWidth={2} />
            </Pressable>
          </View>
          {children}
        </View>
      </View>
    </Modal>
  );
}

// --- Manbalar ---------------------------------------------------------------------

function kindOf(src: AnswerSource): 'doc' | 'law' | 'data' {
  if (src.kind === 'law') return 'law';
  if (src.kind === 'hrm' || src.kind === 'crm' || src.tool || src.marker) return 'data';
  return 'doc';
}

export function SourcesSheet({ visible, onClose, sources, focus, api }: { visible: boolean; onClose: () => void; sources: AnswerSource[]; focus?: string; api: ChatApi }) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const [opening, setOpening] = useState<number | null>(null);

  const open = async (src: AnswerSource, i: number) => {
    const kind = kindOf(src);
    try {
      if (kind === 'law' && src.url && /^https:\/\//i.test(src.url)) {
        await Linking.openURL(src.url);
        return;
      }
      if (kind === 'doc' && src.doc_id) {
        setOpening(i);
        const link = await api.docLink(src.doc_id, `${(src.title || 'hujjat').slice(0, 60)}.pdf`);
        await Linking.openURL(api.absolute(link.url));
      }
    } catch (err) {
      showToast(errorText(t, err) || t('chat.openFailed'));
    } finally {
      setOpening(null);
    }
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={t('chat.sourcesTitle')}>
      <ScrollView style={{ maxHeight: 520 }} contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 8, gap: 8 }}>
        {sources.map((src, i) => {
          const kind = kindOf(src);
          const marker = src.marker || (src.citation_index != null ? String(src.citation_index) : '');
          const focused = !!focus && marker === focus.replace(/^T/, src.marker ? 'T' : '');
          const Icon = kind === 'law' ? Landmark : kind === 'data' ? Database : BookOpen;
          const meta = [
            kind === 'data' ? t('chat.sourceData') : kind === 'law' ? t('chat.sourceLaw') : null,
            src.section,
            src.page ? t('chat.sourcePage', { n: src.page }) : null,
          ]
            .filter(Boolean)
            .join(' · ');
          const tappable = (kind === 'doc' && !!src.doc_id) || (kind === 'law' && !!src.url);
          return (
            <Pressable
              key={`${marker}-${i}`}
              disabled={!tappable}
              onPress={() => void open(src, i)}
              accessibilityRole={tappable ? 'button' : undefined}
              style={({ pressed }) => [s.srcRow, focused ? { borderColor: th.brand } : null, pressed && tappable ? { opacity: 0.7 } : null]}>
              <View style={s.srcIcon}>
                <Icon size={16} color={th.textSoft} strokeWidth={2} />
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={s.srcTitle} numberOfLines={3}>
                  {marker ? <Text style={s.srcMarker}>{`[${marker}] `}</Text> : null}
                  {src.title || src.tool || '—'}
                </Text>
                {meta ? <Text style={s.srcMeta}>{meta}</Text> : null}
                {src.digest ? (
                  <Text style={s.srcDigest} numberOfLines={4}>
                    {src.digest}
                  </Text>
                ) : null}
              </View>
              {opening === i ? <ActivityIndicator size="small" color={th.textMuted} /> : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </Sheet>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.45)' },
    sheet: { backgroundColor: th.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: '88%', paddingTop: 8 },
    grabber: { alignSelf: 'center', width: 36, height: 4, borderRadius: 2, backgroundColor: th.borderStrong, marginBottom: 6 },
    head: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 },
    title: { flex: 1, color: th.text, fontSize: 18, fontWeight: '700' },
    close: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: th.surfaceAlt },
    srcRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', borderWidth: 1, borderColor: th.border, borderRadius: 14, padding: 12 },
    srcIcon: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: th.surfaceAlt },
    srcTitle: { color: th.text, fontSize: 15, lineHeight: 21, fontWeight: '600' },
    srcMarker: { color: th.textMuted, fontWeight: '700' },
    srcMeta: { color: th.textMuted, fontSize: 13, marginTop: 2 },
    srcDigest: { color: th.textSoft, fontSize: 13, lineHeight: 18, marginTop: 4 },
  });
}
