/**
 * Jonli suhbat ichidagi ⚙: ovoz (ayol/erkak), tezlik va "matnni ko'rsatish" - QORONG'I
 * pastki varaq, xuddi shu ekranda.
 *
 * NIMA UCHUN alohida sahifa (`/settings/voice`) emas: boshqa sahifaga o'tish ekranni
 * "fokusdan" chiqaradi - sessiya pauzaga tushib, Barno gapi o'chardi; tezlikni o'zgartirishning
 * eng tabiiy sababi ("juda sekin") aynan javob paytida. Varaq ochiq turganda ham Barno
 * gapiraveradi, yangi ovoz/tezlik KEYINGI bo'lakdan eshitiladi. Yorug' mavzudagi oq sahifa
 * qora ekran ustida "chaqnamaydi".
 *
 * "Ovozni sinash" bu yerda yo'q: u alohida pleyer - jonli suhbat ovozi ustiga tushardi.
 */
import * as Haptics from 'expo-haptics';
import { Check, X } from 'lucide-react-native';
import { Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import type { VoiceId, VoiceSpeed } from '@/features/voice';
import { useVoiceSettings } from '@/features/voice/voiceSettings';
import type { TKey } from '@/i18n';
import { useSafeInsets } from '@/ui/insets';
import { darkTheme as D } from '@/ui/theme';

import { SPEED_KEY } from './voiceText';

const VOICES: { value: VoiceId; title: TKey; testID: string }[] = [
  { value: 'uz_female_calm', title: 'nav.voice.female', testID: 'voice-sheet-female' },
  { value: 'uz_male_news', title: 'nav.voice.male', testID: 'voice-sheet-male' },
];
const SPEEDS: VoiceSpeed[] = ['slow', 'normal', 'fast'];

export interface VoiceSettingsSheetProps {
  visible: boolean;
  onClose: () => void;
  /** Bu tilda ovoz yo'q (ru/en): matn baribir ko'rinadi - kalit o'chiq, izoh bilan. */
  canSpeak: boolean;
}

export function VoiceSettingsSheet({ visible, onClose, canSpeak }: VoiceSettingsSheetProps) {
  const t = useT();
  const insets = useSafeInsets();
  const voice = useVoiceSettings((s) => s.voice);
  const speed = useVoiceSettings((s) => s.speed);
  const showText = useVoiceSettings((s) => s.showText);
  const set = useVoiceSettings((s) => s.set);
  const pick = (patch: Parameters<typeof set>[0]) => {
    void Haptics.selectionAsync().catch(() => {});
    set(patch);
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={s.root}>
        <Pressable style={s.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel={t('common.close')} testID="voice-sheet-backdrop" />
        <View style={[s.sheet, { paddingBottom: 16 + insets.bottom }]} testID="voice-sheet">
          <View style={s.head}>
            <Text style={s.title} accessibilityRole="header">
              {t('nav.voice.settings')}
            </Text>
            <Pressable testID="voice-sheet-close" accessibilityRole="button" accessibilityLabel={t('common.close')} onPress={onClose} hitSlop={8} style={({ pressed }) => [s.close, pressed && s.pressed]}>
              <X size={20} color={D.textSoft} strokeWidth={2} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={s.body}>
            <Text style={s.group}>{t('nav.voice.voice')}</Text>
            <View style={s.card}>
              {VOICES.map((v, i) => (
                <Row key={v.value} testID={v.testID} title={t(v.title)} checked={voice === v.value} first={i === 0} onPress={() => pick({ voice: v.value })} />
              ))}
            </View>
            <Text style={s.group}>{t('nav.voice.speed')}</Text>
            <View style={s.card}>
              {SPEEDS.map((sp, i) => (
                <Row key={sp} testID={`voice-sheet-speed-${sp}`} title={t(SPEED_KEY[sp])} checked={speed === sp} first={i === 0} onPress={() => pick({ speed: sp })} />
              ))}
            </View>
            <View style={[s.card, s.switchRow]}>
              <View style={s.switchText}>
                <Text style={[s.rowTitle, !canSpeak && s.dimmed]}>{t('nav.voice.showText')}</Text>
                {!canSpeak ? <Text style={s.note}>{t('nav.voice.textAlways')}</Text> : null}
              </View>
              <Switch
                testID="voice-sheet-show-text"
                accessibilityLabel={t('nav.voice.showText')}
                value={canSpeak ? showText : true}
                disabled={!canSpeak}
                onValueChange={(v) => pick({ showText: v })}
                trackColor={{ false: D.borderStrong, true: D.brand }}
                thumbColor={D.text}
              />
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function Row({ title, checked, first, onPress, testID }: { title: string; checked: boolean; first: boolean; onPress: () => void; testID: string }) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="radio"
      accessibilityState={{ checked }}
      accessibilityLabel={title}
      onPress={onPress}
      style={({ pressed }) => [s.row, !first && s.rowLine, pressed && { backgroundColor: D.border }]}>
      <Text style={s.rowTitle}>{title}</Text>
      {checked ? <Check size={18} color={D.brand} strokeWidth={2.25} /> : null}
    </Pressable>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  // Ilovadagi boshqa modallar (modals.tsx, drawer) bilan bir xil parda.
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: { backgroundColor: D.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingTop: 8, maxHeight: '80%' },
  head: { flexDirection: 'row', alignItems: 'center', paddingLeft: 20, paddingRight: 8, height: 52 },
  title: { flex: 1, color: D.text, fontSize: 17, lineHeight: 22, fontWeight: '600' },
  close: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  body: { paddingHorizontal: 16, paddingBottom: 8, gap: 8 },
  group: { color: D.textMuted, fontSize: 13, lineHeight: 18, fontWeight: '500', marginTop: 8, marginLeft: 4 },
  card: { backgroundColor: D.surfaceAlt, borderRadius: 14, overflow: 'hidden' },
  row: { minHeight: 48, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  rowLine: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: D.border },
  rowTitle: { color: D.text, fontSize: 16, lineHeight: 21 },
  switchRow: { marginTop: 8, minHeight: 52, paddingHorizontal: 16, paddingVertical: 8, flexDirection: 'row', alignItems: 'center', gap: 12 },
  switchText: { flex: 1, gap: 2 },
  note: { color: D.textMuted, fontSize: 13, lineHeight: 18 },
  dimmed: { opacity: 0.6 },
  pressed: { opacity: 0.8 },
});
