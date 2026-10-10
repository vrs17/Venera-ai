/**
 * Yozish va xotira: yuklangan yozuv telefonda qancha turadi, yuklash navbati va
 * batareya cheklovi (uzoq yig'ilish yozuvi fonda to'xtab qolmasin).
 *
 * "Hozir yuklash" faqat navbatda nimadir bo'lsa ko'rinadi - bo'sh navbatda tugma
 * hech narsa qilmasdi va "nimadir yuklanmay qoldimi?" degan xavotir uyg'otardi.
 * Dev yig'ilmasida audio manba tanlovi (serverning `recording.audioSource`ini bosib o'tadi).
 */
import { BatteryCharging, CloudUpload } from 'lucide-react-native';
import { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { openBatterySettings } from '@/features/recorder/battery';
import { RECORDING_SOURCES } from '@/features/recorder/preset';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { isPending } from '@/features/upload/uploader';
import { useQueueRows } from '@/features/upload/useQueue';
import { useServices } from '@/services';
import { Collapsible, StepList } from '@/ui/Collapsible';
import { Button, Chip } from '@/ui/components';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';

export default function RecordingSettingsScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const services = useServices();
  const keepDays = useSettings((s) => s.keepDays);
  const audioSourceOverride = useSettings((s) => s.audioSourceOverride);
  const set = useSettings((s) => s.set);
  const rows = useQueueRows();
  // Kutayotgan yoki xato bilan to'xtagan - ikkalasi ham hali serverda yo'q.
  const waiting = rows.filter((r) => isPending(r) || r.state === 'failed').length;
  const [busy, setBusy] = useState(false);

  const uploadNow = async () => {
    setBusy(true);
    try {
      await services.uploader.runOnce();
    } catch {
      /* xato qatorning o'zida (lastError) - ro'yxat/yozuv kartasi sababini aytadi */
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}>
      <ListGroup header={t('set.keepTitle')}>
        <ListRow
          testID="keep-0"
          title={t('settings.keep0')}
          titleLines={2}
          right={{ kind: 'check', checked: keepDays === 0 }}
          onPress={() => set({ keepDays: 0 })}
        />
        <ListRow
          testID="keep-7"
          title={t('settings.keep7')}
          titleLines={2}
          right={{ kind: 'check', checked: keepDays === 7 }}
          onPress={() => set({ keepDays: 7 })}
        />
      </ListGroup>

      <ListGroup>
        <ListRow
          testID="settings-queue"
          icon={CloudUpload}
          title={t('set.queueTitle')}
          subtitle={waiting ? t('set.queueN', { n: waiting }) : t('set.queueEmpty')}
          right={
            waiting
              ? {
                  kind: 'node',
                  node: (
                    <Button
                      small
                      variant="secondary"
                      testID="queue-upload"
                      title={t('settings.uploadNow')}
                      loading={busy}
                      onPress={() => void uploadNow()}
                      // Qator foni ham `surfaceAlt` - tugma sahifa foni bilan ajralsin.
                      style={[s.button, { backgroundColor: th.bg, borderColor: th.borderStrong }]}
                    />
                  ),
                }
              : { kind: 'none' }
          }
        />
      </ListGroup>

      <ListGroup>
        <ListRow
          testID="battery-open"
          icon={BatteryCharging}
          title={t('set.battery')}
          subtitle={t('set.batteryWhat')}
          onPress={() => void openBatterySettings()}
        />
      </ListGroup>
      {/* Tizim sozlamasi ochiladi, lekin u yerda NIMA qilish kerakligini ilova aytmasa odam adashadi. */}
      <View style={s.howTo}>
        <Collapsible title={t('set.howTo')} testID="battery-howto">
          <StepList numbered={false} items={[t('record.batteryBody')]} />
        </Collapsible>
      </View>

      {__DEV__ ? (
        <ListGroup header={t('settings.audioSource')}>
          {/* Neytral chip foni `surfaceAlt` - shuning uchun bu yerda karta foni yo'q (sahifa foni). */}
          <View testID="audio-source" style={s.chips}>
            <Chip
              label={t('settings.audioSourceServer')}
              tone={audioSourceOverride == null ? 'accent' : 'neutral'}
              selected={audioSourceOverride == null}
              onPress={() => set({ audioSourceOverride: null })}
            />
            {RECORDING_SOURCES.map((src) => (
              <Chip
                key={src}
                label={src}
                tone={audioSourceOverride === src ? 'accent' : 'neutral'}
                selected={audioSourceOverride === src}
                onPress={() => set({ audioSourceOverride: src })}
              />
            ))}
          </View>
        </ListGroup>
      ) : null}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  button: { borderWidth: StyleSheet.hairlineWidth, paddingHorizontal: 12 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 4 },
  // ListGroup pastki 24 dp oralig'ini qisman qaytaramiz - yo'riqnoma qatorga yopishib tursin.
  howTo: { paddingHorizontal: 4, marginTop: -16, marginBottom: 16 },
});
