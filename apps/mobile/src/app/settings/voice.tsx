/**
 * Ovozli suhbat sozlamalari (`/settings/voice`): Barno ovozi (ayol/erkak), tezlik,
 * jonli rejimda matnni ko'rsatish va "Ovozni sinash".
 *
 * Bu sahifa ham Sozlamalar hub'idan, ham jonli suhbatdagi ⚙ dan ochiladi. Jonli suhbat
 * bu yerda pauzada turadi (mikrofon bo'sh); tanlangan ovoz/tezlik KEYINGI gapdan amal qiladi.
 *
 * "Ovozni sinash" - tanlangan ovoz va tezlikdagi qisqa o'zbekcha namuna; qayta bosilsa
 * to'xtaydi. Sahifadan chiqilsa namuna ham to'xtaydi (fon ovozi qolib ketmasin).
 * Ovoz hozircha faqat o'zbekcha - boshqa tilda pastda shu haqda izoh.
 */
import { Play, Square } from 'lucide-react-native';
import { useEffect } from 'react';
import { ActivityIndicator, ScrollView } from 'react-native';

import { useSettings, useT } from '@/features/settings/settingsStore';
import type { VoiceId, VoiceSpeed } from '@/features/voice';
// Barrel emas: u `useVoiceSession` (expo-audio yozuvchi hook'i) ni ham olib keladi - bu sahifaga keraksiz.
import { PREVIEW_KEY, stopReadAloud, useReadAloud, useReadAloudControls } from '@/features/voice/readAloud';
import { SPEED_KEY } from '@/features/voice/ui/voiceText';
import { useVoiceSettings } from '@/features/voice/voiceSettings';
import type { TKey } from '@/i18n';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';

const VOICES: { value: VoiceId; title: TKey; testID: string }[] = [
  { value: 'uz_female_calm', title: 'nav.voice.female', testID: 'voice-female' },
  { value: 'uz_male_news', title: 'nav.voice.male', testID: 'voice-male' },
];

const SPEEDS: VoiceSpeed[] = ['slow', 'normal', 'fast'];

export default function VoiceSettingsScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const uiLang = useSettings((s) => s.uiLang);
  const voice = useVoiceSettings((s) => s.voice);
  const speed = useVoiceSettings((s) => s.speed);
  const showText = useVoiceSettings((s) => s.showText);
  const set = useVoiceSettings((s) => s.set);
  const preview = useReadAloud((s) => (s.key === PREVIEW_KEY ? s.phase : 'idle'));
  const controls = useReadAloudControls();

  // Sahifadan chiqilsa namuna to'xtaydi (faqat namuna - chatdagi o'qishga tegmaymiz).
  useEffect(
    () => () => {
      if (useReadAloud.getState().key === PREVIEW_KEY) stopReadAloud();
    },
    [],
  );

  const previewRight =
    preview === 'loading'
      ? { kind: 'node' as const, node: <ActivityIndicator size="small" color={th.textMuted} testID="voice-preview-loading" /> }
      : preview === 'playing' || preview === 'paused'
        ? { kind: 'node' as const, node: <Square size={16} color={th.text} fill={th.text} strokeWidth={0} /> }
        : { kind: 'none' as const };

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }} testID="voice-settings-screen">
      <ListGroup header={t('nav.voice.voice')}>
        {VOICES.map((v) => (
          <ListRow
            key={v.value}
            testID={v.testID}
            title={t(v.title)}
            right={{ kind: 'check', checked: voice === v.value }}
            onPress={() => set({ voice: v.value })}
          />
        ))}
      </ListGroup>

      <ListGroup header={t('nav.voice.speed')}>
        {SPEEDS.map((sp) => (
          <ListRow
            key={sp}
            testID={`speed-${sp}`}
            title={t(SPEED_KEY[sp])}
            right={{ kind: 'check', checked: speed === sp }}
            onPress={() => set({ speed: sp })}
          />
        ))}
      </ListGroup>

      <ListGroup>
        {/* ru/en da ovoz yo'q - javob baribir matn bo'lib ko'rinadi: kalit o'chiq, sababi yozilgan. */}
        <ListRow
          testID="voice-show-text"
          title={t('nav.voice.showText')}
          subtitle={uiLang !== 'uz' ? t('nav.voice.textAlways') : null}
          right={{ kind: 'switch', value: uiLang !== 'uz' ? true : showText, disabled: uiLang !== 'uz', onChange: (v) => set({ showText: v }) }}
        />
      </ListGroup>

      <ListGroup footer={uiLang !== 'uz' ? t('nav.voice.uzOnlyFooter') : undefined}>
        <ListRow
          testID="voice-preview"
          icon={Play}
          title={t('nav.voice.preview')}
          right={previewRight}
          accessibilityLabel={preview === 'idle' ? t('nav.voice.preview') : `${t('nav.voice.preview')}, ${t('nav.voice.listenStop')}`}
          onPress={controls.preview}
        />
      </ListGroup>
    </ScrollView>
  );
}
