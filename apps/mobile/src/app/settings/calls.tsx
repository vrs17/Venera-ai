/**
 * Sozlamalar -> Qo'ng'iroq yozuvlari: aniqlashni yoqish, avtomatik yuborish, ruxsat holati,
 * suhbat tili; Samsung'da yozishni yoqish va boshqa ilovadan ulashish yo'riqnomasi (yig'ilgan),
 * maxfiylik eslatmasi.
 *
 * NIMA UCHUN alohida sahifa: Android 10+ da ilovalar qo'ng'iroq ovozini o'zi yoza olmaydi -
 * yozuvni Samsung Telefon qiladi, Barno faqat tayyor faylni topadi. Buni bilmagan odam
 * "yoqdim, lekin hech narsa chiqmayapti" deydi, shuning uchun qadamlar shu yerda.
 *
 * Qatorlar sozlash tartibida: ko'rsatish -> audio ruxsati -> avtomatik yuborish.
 * `?howto=1` (Qo'ng'iroqlar bo'limidagi "Qo'ng'iroqni qanday yozish") - Samsung qadamlari ochiq.
 */
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { LockKeyhole, PhoneCall, Send } from 'lucide-react-native';
import { useCallback, useEffect, useState } from 'react';
import { AppState, ScrollView, StyleSheet, View } from 'react-native';

import type { Lang } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { useCallsOwner } from '@/features/calls/CallAutoSend';
import { useCalls } from '@/features/calls/callsStore';
import { askAudioPermission, callsSupported, enableAutoSend, enableCallDetection } from '@/features/calls/permission';
import { hasAudioReadPermission } from '@/features/entry/nativeEntry';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { Collapsible, StepList } from '@/ui/Collapsible';
import { EmptyState } from '@/ui/EmptyState';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';

const LANGS: Lang[] = ['uz', 'ru', 'en'];

export default function CallsSettingsScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const enabled = useCalls((s) => s.enabled);
  const autoSend = useCalls((s) => s.autoSend);
  const language = useCalls((s) => s.language);
  const lastLanguage = useSettings((s) => s.lastLanguage);
  const configLangs = useAuth((s) => s.config?.languages);
  const { howto } = useLocalSearchParams<{ howto?: string }>();
  const [supported] = useState(callsSupported);
  const [permitted, setPermitted] = useState(() => hasAudioReadPermission());
  useCallsOwner();

  // Tizim sozlamasidan qaytganda ruxsat holati yangilansin.
  const recheck = useCallback(() => setPermitted(hasAudioReadPermission()), []);
  useFocusEffect(recheck);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => s === 'active' && recheck());
    return () => sub.remove();
  }, [recheck]);

  if (!supported) {
    return (
      <View style={[s.root, { backgroundColor: th.bg }]}>
        <EmptyState testID="calls-update" icon={PhoneCall} title={t('calls.updateTitle')} body={t('calls.updateBody')} />
      </View>
    );
  }

  const toggleEnabled = async (v: boolean) => {
    if (!v) {
      useCalls.getState().set({ enabled: false });
      return;
    }
    await enableCallDetection(t);
    recheck();
  };

  const toggleAuto = async (v: boolean) => {
    if (!v) {
      useCalls.getState().set({ autoSend: false });
      return;
    }
    // Har safar ogohlantirish: endi shaxsiy qo'ng'iroqlar ham o'zi ketadi (faqat SHU paytdan keyingilari).
    await enableAutoSend(t);
  };

  const langs = configLangs?.length ? LANGS.filter((l) => configLangs.includes(l)) : LANGS;
  const current = language ?? lastLanguage;

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }} testID="calls-settings-screen">
      <ListGroup>
        <ListRow
          testID="calls-detect"
          icon={PhoneCall}
          title={t('calls.detect')}
          right={{ kind: 'switch', value: enabled, onChange: (v) => void toggleEnabled(v), testID: 'calls-detect-toggle' }}
        />
        <ListRow
          testID="calls-permission-row"
          icon={LockKeyhole}
          title={t('calls.permRow')}
          subtitle={permitted ? t('calls.permGranted') : t('calls.permMissing')}
          subtitleTone={permitted ? undefined : 'warn'}
          onPress={permitted ? undefined : () => void askAudioPermission(t).then(recheck)}
        />
        <ListRow
          testID="calls-auto"
          icon={Send}
          title={t('calls.autoSend')}
          subtitle={autoSend ? t('calls.autoOn') : t('calls.autoOff')}
          disabled={!enabled}
          right={{ kind: 'switch', value: autoSend, onChange: (v) => void toggleAuto(v), disabled: !enabled, testID: 'calls-auto-toggle' }}
        />
      </ListGroup>

      <ListGroup header={t('calls.language')}>
        {langs.map((l) => (
          <ListRow
            key={l}
            testID={`calls-lang-${l}`}
            title={t(`lang.${l}`)}
            right={{ kind: 'check', checked: current === l }}
            onPress={() => useCalls.getState().set({ language: l })}
          />
        ))}
      </ListGroup>

      <View style={s.howTo}>
        <Collapsible title={t('calls.samsungHowTo')} testID="calls-samsung-howto" initiallyOpen={howto === '1'}>
          <StepList items={[t('calls.samsungStep1'), t('calls.samsungStep2'), t('calls.samsungStep3'), t('calls.samsungStep4')]} />
        </Collapsible>
        <Collapsible title={t('calls.shareHowTo')} testID="calls-share-howto">
          <StepList items={[t('calls.shareStep1'), t('calls.shareStep2'), t('calls.shareStep3')]} />
        </Collapsible>
        <Collapsible title={t('calls.privacy')} testID="calls-privacy">
          <StepList
            numbered={false}
            items={[t('calls.privacy1'), t('calls.privacy2'), t('calls.privacy3'), t('calls.privacy4'), t('calls.privacy5')]}
          />
        </Collapsible>
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  howTo: { paddingHorizontal: 4, gap: 4 },
});
