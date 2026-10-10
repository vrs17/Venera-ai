/**
 * "Jonli" - Barno bilan ovozli suhbat (Claude ovozli rejimi kabi), `/voice`.
 *
 *   tepada    ⚙ ovoz sozlamalari (shu ekrandagi qorong'i varaq - suhbat to'xtamaydi)
 *   o'rtada   bo'sh: ✦ + "Gaplashamiz, Yusuf"; keyin - suhbat matni (chat kabi)
 *   pastda    ko'tariluvchi tuman (ko'k - siz, to'q sariq - Barno), holat yozuvi,
 *             [Pro]  (mikrofon)  [quloq] [✕]
 *
 * Oqim (dvigatel `useVoiceSession` da): gapirasiz -> ~1 s jimlik -> matnga -> chat
 * (AYNI suhbat, savollar oddiy chatda ham ko'rinadi) -> kutish klipi -> javob gapma-gap
 * o'qiladi. Barno gapirayotganda gapirsangiz yoki matnga tegsangiz - to'xtaydi va tinglaydi.
 *
 * Ekran doim qorong'i: tuman va katta matn qora fonda o'qiladi (ilova mavzusidan qat'i nazar).
 * ✕ va Android "orqaga" bitta yo'l: sessiya yopiladi (mikrofon, audio rejim qaytadi), keyin
 * ekran yopiladi.
 */
import * as Haptics from 'expo-haptics';
import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { Settings } from 'lucide-react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BackHandler, Pressable, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '@/features/auth/authStore';
import { firstName } from '@/features/nav/AppDrawer';
import { useT } from '@/features/settings/settingsStore';
import { useVoiceSession, useVoiceSettings, type VoiceSnapshot, type VoiceStatus } from '@/features/voice';
import { RoundIcon, VoiceControls } from '@/features/voice/ui/VoiceControls';
import { VoiceFog } from '@/features/voice/ui/VoiceFog';
import { VoiceSettingsSheet } from '@/features/voice/ui/VoiceSettingsSheet';
import { stateText } from '@/features/voice/ui/voiceText';
import { VoiceTranscript } from '@/features/voice/ui/VoiceTranscript';
import { useSafeInsets } from '@/ui/insets';
import { darkTheme as D } from '@/ui/theme';

/**
 * ✕ shuncha kutadi, keyin baribir yopiladi. NIMA UCHUN: tozalash (mikrofon to'xtashi, audio
 * rejim) native chaqiruvlar - biri osilib qolsa odam ekranda qamalib qolardi. Sessiya
 * tozalashni fonda tugatadi (unmount ham `end()` chaqiradi).
 */
const END_WAIT_MS = 600;

export default function VoiceScreen() {
  const t = useT();
  const insets = useSafeInsets();
  const { snap, actions, subscribeLevel } = useVoiceSession();
  const showText = useVoiceSettings((s) => s.showText);
  const name = firstName(useAuth((s) => s.user)?.fullName);
  const [sheet, setSheet] = useState(false);

  // ✕ ikki marta bosilsa ham (yoki "orqaga" bilan birga) ekran bir marta yopiladi.
  const ending = useRef(false);
  const end = useCallback(async () => {
    if (ending.current) return;
    ending.current = true;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    await Promise.race([actions.end().catch(() => {}), new Promise<void>((resolve) => setTimeout(resolve, END_WAIT_MS))]);
    if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [actions]);

  // Android "orqaga" = ✕ (mikrofon ochiq qolib ketmasin) - faqat ekran FOKUSDA bo'lsa.
  // Holat paneli ham shu paytda yorug' (boshqa sahifada oq matn ko'rinmasdi).
  const [focused, setFocused] = useState(true);
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      const sub = BackHandler.addEventListener('hardwareBackPress', () => {
        void end();
        return true;
      });
      return () => {
        sub.remove();
        setFocused(false);
      };
    }, [end]),
  );

  useStatusHaptics(snap);

  const hasTurns = snap.turnIds.length > 0 || !!snap.pendingText || snap.status === 'transcribing';
  // Matn ko'rinadi: sozlamada yoqilgan BO'LSA yoki javob ovozda to'liq aytilmaydigan bo'lsa
  // (ru/en, xato, uzun javob, ishonchsiz matn) - aks holda javob hech qayerda yo'q bo'lardi.
  const transcriptMode = hasTurns && (showText || !snap.canSpeak || !!snap.pendingText || snap.textOnly);
  // "Matnsiz" rejimda suhbat boshlangach sarlavha = holat (pastdagi yozuv takrorlamaydi).
  const stateInTitle = !transcriptMode && hasTurns;
  // Quloq rejimida telefon yuzda - yonoq tegishi Barnoni to'xtatmasin (faqat ovoz bilan bo'linadi).
  const tapToInterrupt = !snap.earpiece;

  return (
    <View style={s.root} testID="voice-screen">
      {focused ? <StatusBar style="light" /> : null}
      <VoiceFog subscribeLevel={subscribeLevel} status={snap.status} micMuted={snap.micMuted} />

      <View style={[s.top, { marginTop: insets.top }]}>
        <RoundIcon testID="voice-settings" label={t('nav.voice.settings')} icon={Settings} size={44} bg="transparent" color={D.textSoft} onPress={() => setSheet(true)} />
      </View>

      <View style={s.middle}>
        {transcriptMode ? (
          <VoiceTranscript snap={snap} onInterrupt={actions.interrupt} onSendPending={actions.sendPending} tapToInterrupt={tapToInterrupt} />
        ) : (
          // Matnsiz rejimda ham o'rtaga tegish Barnoni to'xtatadi (matn rejimidagi kabi).
          <Pressable
            style={s.greeting}
            testID="voice-greeting"
            accessible={false}
            disabled={!tapToInterrupt || !(snap.status === 'speaking' || snap.holdText)}
            onPress={actions.interrupt}>
            <Text style={s.spark} accessibilityElementsHidden importantForAccessibility="no">
              ✦
            </Text>
            <Text style={s.hello} numberOfLines={stateInTitle ? 3 : 2} accessibilityRole="header" testID="voice-title">
              {stateInTitle ? stateText(snap, t) : name ? t('nav.voice.hello', { name }) : t('nav.voice.helloNoName')}
            </Text>
            {/* ru/en: boshidanoq aytamiz - javob ovoz emas, matn bo'ladi (aks holda 6-12 s jim kutib ajablanardi). */}
            {!snap.canSpeak && !stateInTitle ? (
              <Text style={s.sub} testID="voice-text-only-note">
                {t('nav.voice.uzOnlyShort')}
              </Text>
            ) : null}
          </Pressable>
        )}
      </View>

      <View style={{ paddingBottom: insets.bottom + 16 }}>
        <VoiceControls snap={snap} actions={actions} subscribeLevel={subscribeLevel} onEnd={() => void end()} stateInTitle={stateInTitle} />
      </View>

      <VoiceSettingsSheet visible={sheet} onClose={() => setSheet(false)} canSpeak={snap.canSpeak} />
    </View>
  );
}

/**
 * Sezgi: gap tugadi (tinglash -> matnga) - yengil "tik"; bo'lib gapirish (Barno to'xtadi
 * va tinglayapti) - yengil zarba; xato - ogohlantirish. Telefon qo'lda bo'lmasa ham
 * ekranga qaramay holatni sezish mumkin.
 */
function useStatusHaptics(snap: VoiceSnapshot) {
  const prev = useRef<VoiceStatus>(snap.status);
  useEffect(() => {
    const from = prev.current;
    const to = snap.status;
    prev.current = to;
    if (from === to) return;
    if (from === 'listening' && to === 'transcribing') {
      void Haptics.selectionAsync().catch(() => {});
    } else if ((from === 'speaking' || from === 'thinking') && to === 'listening' && snap.hearing) {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    } else if (to === 'error') {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
    }
  }, [snap.status, snap.hearing]);
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: D.bg },
  top: { height: 52, paddingHorizontal: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end' },
  middle: { flex: 1 },
  greeting: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 14, transform: [{ translateY: -32 }] },
  spark: { fontSize: 44, lineHeight: 48, color: D.brand },
  hello: { fontSize: 28, lineHeight: 34, fontWeight: '600', color: D.text, textAlign: 'center', paddingHorizontal: 32 },
  sub: { fontSize: 15, lineHeight: 21, color: D.textSoft, textAlign: 'center', paddingHorizontal: 40 },
});
