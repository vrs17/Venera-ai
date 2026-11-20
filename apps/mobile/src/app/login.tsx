/**
 * Kirish - Mini App'dagi kabi: belgi, "Barno", "BRB-Tech ID bilan bir marta kiring".
 *
 * ASOSIY YO'L (server SSO sozlangan bo'lsa) - «BRB-Tech ID bilan kirish»: PKCE verifier
 * SecureStore'ga yoziladi va kirish TIZIM BRAUZERIDA ochiladi; server ilovaga
 * `venera-rec://sso?sso=<kod>` bilan qaytaradi va `app/sso.tsx` sessiyani tugatadi
 * (`features/auth/sso.ts`). Login + parol - zahira (`users.yaml`), faqat server ruxsat bersa.
 *
 * `POST /auth/login` (HRM/CRM ulanishlari ham shu yerda yangilanadi) -> qurilma
 * ro'yxati (`POST /auth/devices`, uzoq sessiya - faqat yig'ilishlar bo'limi yoqilgan
 * odamlarga; boshqalar 12 soatlik token bilan ishlaydi) -> chat.
 * Yig'ilish konfigi bo'lmasa (bo'lim yoqilmagan) - kirish to'xtamaydi.
 */
import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import * as SecureStore from 'expo-secure-store';
import { router } from 'expo-router';
import { Eye, EyeOff } from 'lucide-react-native';
import { useEffect, useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import type { SsoConfig } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { createPkce, saveVerifier, ssoStartUrl } from '@/features/auth/sso';
import { useT } from '@/features/settings/settingsStore';
import { openPrivacyPolicy } from '@/lib/privacy';
import { deviceInfo, useServices } from '@/services';
import { Banner, Button } from '@/ui/components';
import { useTheme, type Theme } from '@/ui/theme';

export default function LoginScreen() {
  const t = useT();
  const th = useTheme();
  const s = useMemo(() => makeStyles(th), [th]);
  const services = useServices();
  const expired = useAuth((x) => x.expired);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // BRB-Tech ID: server aytgan yo'llar. Yuklanmaguncha (yoki eski server) - faqat parol shakli.
  const [sso, setSso] = useState<SsoConfig | null>(null);
  const [ssoBusy, setSsoBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    services.auth
      .ssoConfig()
      .then((cfg) => alive && setSso(cfg))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [services]);

  const ssoEnabled = !!sso?.enabled;
  const localEnabled = !sso || sso.localLoginEnabled !== false;

  const signInWithSso = async () => {
    if (ssoBusy || !sso) return;
    setSsoBusy(true);
    setError(null);
    try {
      const { verifier, challenge } = await createPkce({
        getRandomBytes: (n) => Crypto.getRandomBytes(n),
        sha256Base64: (data) =>
          Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, data, { encoding: Crypto.CryptoEncoding.BASE64 }),
      });
      await saveVerifier(SecureStore, verifier);
      await Linking.openURL(ssoStartUrl(services.apiBaseUrl, sso, challenge));
    } catch {
      setError(t('login.ssoFailed'));
    } finally {
      setSsoBusy(false);
    }
  };

  const submit = async () => {
    if (busy || !username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const res = await services.session.login(username, password, deviceInfo(services));
      try {
        useAuth.getState().setConfig(await services.meetings.config());
      } catch {
        // Yig'ilishlar bo'limi yoqilmagan yoki keyin olinadi - chatga kirish to'xtamaydi.
        useAuth.getState().setConfig(null);
      }
      useAuth.getState().setSignedIn(res.user);
      void services.uploader.runOnce().catch(() => {});
      setTimeout(() => router.replace('/'), 0);
    } catch (e) {
      if (e instanceof ApiError && e.isNetwork) setError(t('login.network'));
      else if (e instanceof ApiError) setError(e.message);
      else setError(t('common.error'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: th.bg }}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
          <View style={s.hero}>
            <View style={s.spark}>
              <Text style={{ color: th.brand, fontSize: 30 }}>✦</Text>
            </View>
            <Text style={s.title}>Barno</Text>
            <Text style={s.subtitle}>{ssoEnabled ? t('login.ssoSubtitle') : t('login.subtitle')}</Text>
          </View>
          {expired ? <Banner tone="warn" text={t('list.sessionExpired')} /> : null}
          {ssoEnabled ? (
            <View style={{ marginBottom: localEnabled ? 8 : 0 }}>
              <Button testID="login-sso" title={t('login.sso')} loading={ssoBusy} onPress={() => void signInWithSso()} />
              {localEnabled ? <Text style={s.or}>{t('login.or')}</Text> : null}
            </View>
          ) : null}
          {error && !localEnabled ? <Banner tone="bad" text={error} testID="login-error" /> : null}
          {localEnabled ? (
          <>
          <Text style={s.label}>{t('login.username')}</Text>
          <TextInput
            testID="login-username"
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="username"
            placeholder="a.karimov"
            placeholderTextColor={th.textFaint}
            style={s.input}
            returnKeyType="next"
          />
          <Text style={s.label}>{t('login.password')}</Text>
          <View style={s.pwRow}>
            <TextInput
              testID="login-password"
              value={password}
              onChangeText={setPassword}
              secureTextEntry={!show}
              autoComplete="password"
              style={[s.input, { flex: 1, marginBottom: 0, borderWidth: 0 }]}
              onSubmitEditing={() => void submit()}
              returnKeyType="go"
            />
            <Pressable onPress={() => setShow((v) => !v)} hitSlop={8} accessibilityRole="button" style={s.eye}>
              {show ? <EyeOff size={20} color={th.textMuted} /> : <Eye size={20} color={th.textMuted} />}
            </Pressable>
          </View>
          {error ? <Banner tone="bad" text={error} testID="login-error" /> : null}
          <Button
            testID="login-submit"
            variant={ssoEnabled ? 'secondary' : undefined}
            title={t('login.submit')}
            loading={busy}
            disabled={!username.trim() || !password}
            onPress={() => void submit()}
          />
          </>
          ) : null}
          <Button variant="ghost" style={{ marginTop: 12 }} title={t('login.recordWithout')} onPress={() => router.push('/record?src=app')} />
          {/* Google Play: siyosat kirishdan OLDIN ham o'qilishi kerak (`lib/privacy.ts`). */}
          <Pressable
            testID="login-privacy"
            onPress={() => void openPrivacyPolicy()}
            accessibilityRole="link"
            hitSlop={8}
            style={s.privacy}>
            <Text style={s.privacyText}>{t('legal.privacy')}</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    wrap: { padding: 24, paddingTop: 40, flexGrow: 1, justifyContent: 'center' },
    hero: { alignItems: 'center', marginBottom: 28 },
    spark: { width: 72, height: 72, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: th.brandSoft, marginBottom: 14 },
    title: { color: th.text, fontSize: 28, fontWeight: '800', marginBottom: 6 },
    subtitle: { color: th.textMuted, fontSize: 15, textAlign: 'center', lineHeight: 21 },
    label: { color: th.textSoft, fontSize: 14, fontWeight: '600', marginBottom: 6 },
    input: {
      height: 50,
      borderRadius: 14,
      backgroundColor: th.surfaceAlt,
      color: th.text,
      fontSize: 16,
      paddingHorizontal: 14,
      marginBottom: 16,
    },
    pwRow: { flexDirection: 'row', alignItems: 'center', borderRadius: 14, backgroundColor: th.surfaceAlt, marginBottom: 20 },
    eye: { width: 48, height: 50, alignItems: 'center', justifyContent: 'center' },
    or: { color: th.textFaint, fontSize: 13, textAlign: 'center', marginTop: 14, marginBottom: 6 },
    privacy: { alignSelf: 'center', marginTop: 16, paddingVertical: 6, paddingHorizontal: 12 },
    privacyText: { color: th.textMuted, fontSize: 13, textDecorationLine: 'underline' },
  });
}
