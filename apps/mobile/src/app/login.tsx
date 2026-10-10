/**
 * Kirish - Mini App'dagi kabi: belgi, "Barno", "HRM / CRM login bilan bir marta kiring".
 *
 * `POST /auth/login` (HRM/CRM ulanishlari ham shu yerda yangilanadi) -> qurilma
 * ro'yxati (`POST /auth/devices`, uzoq sessiya - faqat yig'ilishlar bo'limi yoqilgan
 * odamlarga; boshqalar 12 soatlik token bilan ishlaydi) -> chat.
 * Yig'ilish konfigi bo'lmasa (bo'lim yoqilmagan) - kirish to'xtamaydi.
 */
import { router } from 'expo-router';
import { Eye, EyeOff } from 'lucide-react-native';
import { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import { useAuth } from '@/features/auth/authStore';
import { useT } from '@/features/settings/settingsStore';
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
            <Text style={s.subtitle}>{t('login.subtitle')}</Text>
          </View>
          {expired ? <Banner tone="warn" text={t('list.sessionExpired')} /> : null}
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
          <Button testID="login-submit" title={t('login.submit')} loading={busy} disabled={!username.trim() || !password} onPress={() => void submit()} />
          <Button variant="ghost" style={{ marginTop: 12 }} title={t('login.recordWithout')} onPress={() => router.push('/record?src=app')} />
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
  });
}
