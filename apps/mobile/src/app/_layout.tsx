/**
 * Ildiz: provayderlar (QueryClient, Services, RecorderProvider), kirish
 * himoyasi va ishga tushish ishlari (spec 7.3).
 *
 * Asosiy ekran (`index`) - Barno bilan native suhbat. U va yig'ilish bo'limi
 * (`meetings`, `meeting/[id]`, `action-items`) hamda Sozlamalar hub'i va uning
 * ichki sahifalari (`settings/*`) - kirgandan keyin; kirilmagan bo'lsa `login`.
 *
 * `record` ekrani HIMOYALANMAGAN: yozish hech qachon login yoki tarmoqni
 * kutmaydi (spec 7.5). Sessiya yo'q bo'lsa yozuv navbatda turadi va
 * kirgandan keyin yuklanadi.
 */
import { MutationCache, QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import * as Network from 'expo-network';
import * as QuickActions from 'expo-quick-actions';
import { router, Stack, useRootNavigationState } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { AppState, Text, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import { useAuth } from '@/features/auth/authStore';
import { CallAutoSend } from '@/features/calls/CallAutoSend';
import { useCrmStore } from '@/features/crm/crmStore';
import { setTrustedKey } from '@/features/entry/nativeEntry';
import { hrefFromAction, installRecordShortcut, withEntryNonce } from '@/features/entry/quickActions';
import { ensureInstallKey } from '@/features/entry/trustedKey';
import { RecorderProvider } from '@/features/recorder/RecorderProvider';
import { useSettings, useT } from '@/features/settings/settingsStore';
// Bu import modulni yuklaydi - backgroundTask.ts modul darajasida defineTask() chaqiradi.
import { registerUploadTask } from '@/features/upload/backgroundTask';
import { makeT } from '@/i18n';
import { clearExports } from '@/lib/paths';
import { getAppServices, ServicesProvider, useServices, type Services } from '@/services';
import { toastError } from '@/ui/errors';
import { useTheme } from '@/ui/theme';

void SplashScreen.preventAutoHideAsync().catch(() => {});

/**
 * Deep link (yon tugma `venera-rec://record`, plitka, yorliq) sovuq ishga tushirsa ham
 * ostida asosiy ekran (chat) bo'lsin: aks holda stekda yolg'iz `/record`, to'xtatgandan
 * keyin yolg'iz `/meeting/<id>` qolib, "Orqaga" ilovadan chiqarardi.
 */
export const unstable_settings = { anchor: 'index' };

const queryClient = new QueryClient({
  // Mutatsiya xatosi jim qolmasin (nom, spiker, vazifa, xulosa...): kod -> i18n toast.
  mutationCache: new MutationCache({
    onError: (err, _vars, _ctx, mutation) => {
      if (mutation.meta?.silentError) return;
      toastError(err, useSettings.getState().uiLang);
    },
  }),
  defaultOptions: {
    queries: {
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      staleTime: 5_000,
    },
  },
});

export default function RootLayout() {
  const [services, setServices] = useState<Services | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Oldingi seansda ulashilgan fayllar (eksport keshi) - ilova ochilganda tozalanadi: ulashish
    // oynasi allaqachon yopilgan, qabul qilgan ilova faylni o'ziga olgan.
    clearExports();
    getAppServices()
      .then(setServices)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => void SplashScreen.hideAsync().catch(() => {}));
  }, []);

  if (error) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <Text>{error}</Text>
      </View>
    );
  }
  if (!services) return null;

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ServicesProvider services={services}>
          <RecorderProvider>
            <Bootstrap />
            {/* Qo'ng'iroq yozuvlarini avtomatik yuborish: hech narsa chizmaydi, shartlar bajarilsa skanerlaydi. */}
            <CallAutoSend />
            <AppStack />
          </RecorderProvider>
        </ServicesProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}

function AppStack() {
  const status = useAuth((s) => s.status);
  const th = useTheme();
  const t = useT();
  if (status === 'unknown') return null;
  const signedIn = status === 'signedIn';
  return (
    <>
      <StatusBar style={th.dark ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          // Claude uslubi: sarlavha sahifa bilan bir rangda, soya chizig'isiz - "tinch" ko'rinish.
          headerShadowVisible: false,
          headerStyle: { backgroundColor: th.bg },
          headerTintColor: th.text,
          headerTitleStyle: { fontSize: 18, fontWeight: '600' },
          contentStyle: { backgroundColor: th.bg },
        }}>
        <Stack.Protected guard={signedIn}>
          {/* Chat o'z sarlavhasini va xavfsiz zonasini o'zi chizadi. */}
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="meetings" options={{ title: t('nav.recordings') }} />
          <Stack.Screen name="meeting/[id]" options={{ title: '' }} />
          <Stack.Screen name="action-items" options={{ title: t('list.myTasks') }} />
          {/* Sozlamalar: hub + har qator o'z sahifasi (URL `/settings` o'zgarmaydi). */}
          <Stack.Screen name="settings/index" options={{ title: t('settings.title') }} />
          <Stack.Screen name="settings/account" options={{ title: t('set.profile') }} />
          <Stack.Screen name="settings/connections" options={{ title: t('settings.connections') }} />
          <Stack.Screen name="settings/memory" options={{ title: t('set.memory.title') }} />
          <Stack.Screen name="settings/quick" options={{ title: t('settings.quick') }} />
          <Stack.Screen name="settings/recording" options={{ title: t('set.recording') }} />
          <Stack.Screen name="settings/language" options={{ title: t('set.language') }} />
          <Stack.Screen name="settings/theme" options={{ title: t('settings.theme') }} />
          <Stack.Screen name="settings/about" options={{ title: t('settings.about') }} />
          <Stack.Screen name="settings/voice" options={{ title: t('nav.voice.settingsTitle') }} />
          <Stack.Screen name="settings/calls" options={{ title: t('calls.settingsTitle') }} />
          <Stack.Screen name="settings/voice-sample" options={{ title: t('vs.title') }} />
          {/* "Ulashish -> Barno AI": kirilmagan bo'lsa login chiqadi, fayllar imports/ da kutadi (chiqishda o'chiriladi). */}
          <Stack.Screen name="import" options={{ title: t('calls.import.title') }} />
          {/* Jonli ovozli suhbat: to'liq ekran, doim qorong'i, o'z tugmalari bor (✕ / orqaga = tugatish). */}
          <Stack.Screen name="voice" options={{ headerShown: false, presentation: 'fullScreenModal', animation: 'fade', gestureEnabled: false }} />
        </Stack.Protected>
        <Stack.Protected guard={!signedIn}>
          <Stack.Screen name="login" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Screen name="record" options={{ title: t('record.title') }} />
      </Stack>
    </>
  );
}

/** Ishga tushish va fon triggerlari: sessiya, installKey, shortcut, yuklash. */
function Bootstrap() {
  const services = useServices();
  const qc = useQueryClient();
  const status = useAuth((s) => s.status);
  const uiLang = useSettings((s) => s.uiLang);
  const navState = useRootNavigationState();
  const pendingHref = useRef<string | null>(null);
  const initialHandled = useRef(false);

  // Sessiya bormi (tarmoqsiz) + installKey + app shortcut.
  useEffect(() => {
    let alive = true;
    (async () => {
      const has = await services.session.hasSession();
      if (!alive) return;
      if (has) useAuth.getState().setSignedIn();
      else useAuth.getState().setSignedOut(false);
      const key = await ensureInstallKey({
        store: services.tokens,
        randomBytes: (n) => Crypto.getRandomBytes(n),
        setNativeKey: setTrustedKey,
      });
      await installRecordShortcut(key, makeT(useSettings.getState().uiLang)('settings.shortcutTitle'));
      await registerUploadTask();
    })().catch(() => {
      if (alive && useAuth.getState().status === 'unknown') useAuth.getState().setSignedOut(false);
    });
    return () => {
      alive = false;
    };
  }, [services]);

  // Ilova tili o'zgarsa yorliq nomi ham o'zgarsin.
  useEffect(() => {
    let alive = true;
    (async () => {
      const key = await services.tokens.getInstallKey();
      if (alive && key) await installRecordShortcut(key, makeT(uiLang)('settings.shortcutTitle'));
    })().catch(() => {});
    return () => {
      alive = false;
    };
  }, [services, uiLang]);

  // Chiqish / sessiya tugashi: boshqa odam shu telefonda kirsa oldingi
  // foydalanuvchining yig'ilish nomlari keshdan bir lahza ham ko'rinmasin.
  useEffect(() => {
    if (status === 'signedOut') {
      qc.clear();
      useCrmStore.getState().reset();
    }
  }, [status, qc]);

  // Konfig (limitlar, shablonlar, yozish sozlamasi) - kirgandan keyin.
  useEffect(() => {
    if (status !== 'signedIn') return;
    services.meetings
      .config()
      .then((c) => useAuth.getState().setConfig(c))
      .catch(() => {});
    if (!useAuth.getState().user) {
      services.auth
        .me()
        .then((u) => useAuth.getState().setSignedIn(u))
        .catch(() => {});
    }
    void services.uploader.runOnce().catch(() => {});
  }, [status, services, uiLang]);

  // Yuklash triggerlari: AppState active, tarmoq qaytishi.
  useEffect(() => {
    const kick = () => void services.uploader.runOnce().catch(() => {});
    const app = AppState.addEventListener('change', (s) => s === 'active' && kick());
    let net: { remove(): void } | null = null;
    try {
      net = Network.addNetworkStateListener((s) => {
        if (s.isConnected && s.isInternetReachable !== false) kick();
      });
    } catch {
      net = null;
    }
    return () => {
      app.remove();
      net?.remove();
    };
  }, [services]);

  // App shortcut "Yozishni boshlash": navigatsiya tayyor bo'lgach o'tamiz.
  useEffect(() => {
    if (!initialHandled.current) {
      initialHandled.current = true;
      const initial = hrefFromAction(QuickActions.initial);
      pendingHref.current = initial ? withEntryNonce(initial) : null;
    }
    const sub = QuickActions.addListener((a) => {
      const raw = hrefFromAction(a);
      if (!raw) return;
      // Har bosish yangi nonce: Record ekrani ochiq bo'lsa ham bir xil href qayta ishlansin.
      const href = withEntryNonce(raw);
      if (navState?.key) router.navigate(href as never);
      else pendingHref.current = href;
    });
    return () => sub.remove();
  }, [navState?.key]);

  useEffect(() => {
    if (navState?.key && pendingHref.current && status !== 'unknown') {
      const href = pendingHref.current;
      pendingHref.current = null;
      router.navigate(href as never);
    }
  }, [navState?.key, status]);

  return null;
}
