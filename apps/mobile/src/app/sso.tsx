/**
 * BRB-Tech ID dan qaytish: `venera-rec://sso?sso=<kod>` (tizim brauzeri ilovani ochadi).
 *
 * Kod + saqlangan PKCE verifier -> `POST /auth/sso/exchange` -> sessiya va qurilma
 * (`session.loginWith`, parol bilan kirishdagi kabi) -> chat. Verifier bir martalik va 10
 * daqiqa yashaydi (`features/auth/sso.ts`); yo'q bo'lsa (boshqa ilova boshlagan kirish,
 * eskirgan) - kirish ekrani xabar bilan. `?sso_error=` - Keycloak/server rad etdi.
 */
import * as SecureStore from 'expo-secure-store';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import { useAuth } from '@/features/auth/authStore';
import { takeVerifier } from '@/features/auth/sso';
import { useT } from '@/features/settings/settingsStore';
import { deviceInfo, useServices } from '@/services';
import { Banner, Button } from '@/ui/components';
import { useTheme } from '@/ui/theme';

type Raw = { sso?: string | string[]; sso_error?: string | string[] };

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? '';
}

export default function SsoReturnScreen() {
  const t = useT();
  const th = useTheme();
  const services = useServices();
  const raw = useLocalSearchParams<Raw>();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = first(raw.sso);
    const failed = first(raw.sso_error);
    void (async () => {
      if (failed || !code) {
        setError(failed === 'blocked' ? t('login.ssoBlocked') : t('login.ssoFailed'));
        return;
      }
      const verifier = await takeVerifier(SecureStore);
      if (!verifier) {
        setError(t('login.ssoExpired'));
        return;
      }
      try {
        const res = await services.auth.ssoExchange({ code, verifier });
        await services.session.loginWith(res, deviceInfo(services));
        try {
          useAuth.getState().setConfig(await services.meetings.config());
        } catch {
          // Yig'ilishlar bo'limi yoqilmagan - chatga kirish to'xtamaydi.
          useAuth.getState().setConfig(null);
        }
        useAuth.getState().setSignedIn(res.user);
        void services.uploader.runOnce().catch(() => {});
        setTimeout(() => router.replace('/'), 0);
      } catch (e) {
        if (e instanceof ApiError && e.isNetwork) setError(t('login.network'));
        else if (e instanceof ApiError && e.status === 400) setError(t('login.ssoExpired'));
        else setError(t('login.ssoFailed'));
      }
    })();
  }, [raw.sso, raw.sso_error, services, t]);

  return (
    <SafeAreaView style={[styles.wrap, { backgroundColor: th.bg }]}>
      {error ? (
        <View style={styles.box}>
          <Banner tone="bad" text={error} testID="sso-error" />
          <Button title={t('login.ssoBack')} onPress={() => router.replace('/login')} />
        </View>
      ) : (
        <View style={styles.center}>
          <ActivityIndicator color={th.brand} />
          <Text style={{ color: th.textMuted, marginTop: 12, fontSize: 15 }}>{t('login.ssoFinishing')}</Text>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  box: { flex: 1, padding: 24, justifyContent: 'center' },
});
