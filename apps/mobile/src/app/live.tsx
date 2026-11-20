/**
 * "Jonli suhbat" - Barno bilan jonli ovozli qo'ng'iroq (Speko agenti), `/live`. Chatdagi asosiy ovoz tugmasi.
 *
 * Saytdagi llm.brb-tech.uz/barno sahifasi WebView ichida "ilova rejimi"da ochiladi (`?app=1&autostart=1`):
 * qo'ng'iroq dvigateli bitta (sayt + Speko SDK, WebRTC) - ilovada ham, brauzerda ham bir xil ishlaydi va bir
 * joyda yangilanadi. Ilova - qobiq: ✕, mikrofon ruxsati, token, ekran yoqiq, "orqaga" va fon.
 *
 * TOKEN: sayt bilan bir xil server JWT si (`session.getToken()`), sahifaga faqat xotirada
 * (`features/live/bridge.ts`). Android'da "sahifadan oldin" skript kafolatlanmaydi, shuning uchun sahifa
 * `ready` deydi va token shunga javoban ham beriladi. WebView faqat shu sayt manzilida yuradi
 * (`originWhitelist`) - boshqa manzil tizim brauzerida ochiladi.
 *
 * MIKROFON ruxsati WebView'dan OLDIN so'raladi: ruxsat oynasi qo'ng'iroq o'rtasida chiqmasin (WebView o'zi
 * so'rasa ilova bir lahza "fonga" o'tadi).
 *
 * TUGATISH: ✕ - qo'ng'iroq ketayotgan bo'lsa avval sahifa ichida tugatiladi (Speko'da daqiqa hisobi to'xtaydi),
 * keyin ekran yopiladi. "Orqaga" - qo'ng'iroqni tugatadi (rahmat sahifasi), qo'ng'iroq yo'q bo'lsa yopadi.
 * Ilova `BACKGROUND_END_MS` dan ko'p fonda tursa ham tugatiladi: fonda mikrofon ishlamaydi, daqiqa ketaverardi.
 *
 * "Ovozli rejim" (`/voice`, chatdagi «Ovozli» chipi) - alohida: chat ichidagi ovozli savol-javob.
 */
import { router, useFocusEffect } from 'expo-router';
import { LogIn, MicOff, RotateCw, WifiOff, X } from 'lucide-react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, BackHandler, Linking, StyleSheet, View } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';

import {
  ACTIVE_STATUSES,
  END_SCRIPT,
  liveOrigin,
  liveUrl,
  parseLiveMessage,
  sameOrigin,
  tokenScript,
} from '@/features/live/bridge';
import type { Session } from '@/features/auth/session';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { hasMicPermission, keepScreenOn, requestMicPermission } from '@/features/voice/native';
import { stopReadAloud } from '@/features/voice/readAloud';
import { useServices } from '@/services';
import { Loading } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { IconButton } from '@/ui/IconButton';
import { useSafeInsets } from '@/ui/insets';
import { useTheme } from '@/ui/theme';

/** ✕ bosilganda sahifa qo'ng'iroqni tugatib ulgurishi uchun (Speko sessiyasi yopiladi), keyin ekran yopiladi. */
const END_WAIT_MS = 500;
/** Ilova shuncha fonda tursa qo'ng'iroq tugatiladi. Qisqa chiqishlar (tizim oynasi) qo'ng'iroqni uzmaydi. */
export const BACKGROUND_END_MS = 8000;

type Phase = 'starting' | 'ready' | 'denied' | 'failed' | 'auth';

/** Sahifadan oldin: mikrofon ruxsati (qo'ng'iroq o'rtasida oyna chiqmasin), keyin token. */
async function preflight(session: Session): Promise<{ phase: Phase; token: string | null }> {
  const mic = await requestMicPermission().catch(() => false);
  if (!mic) return { phase: 'denied', token: null };
  try {
    return { phase: 'ready', token: await session.getToken() };
  } catch {
    return { phase: 'auth', token: null };
  }
}

export default function LiveScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const { apiBaseUrl, session, appVersion } = useServices();
  const lang = useSettings((s) => s.uiLang);
  const origin = liveOrigin(apiBaseUrl);
  // Manzil ochilishda bir marta: mavzu yoki til qo'ng'iroq o'rtasida o'zgarsa sahifa qayta yuklanmasin.
  const [url] = useState(() => liveUrl(apiBaseUrl, { theme: th.dark ? 'dark' : 'light', lang }));
  const [phase, setPhase] = useState<Phase>('starting');
  const [token, setToken] = useState<string | null>(null);
  /** WebView kaliti: oshsa sahifa yangi token bilan qaytadan ochiladi (401 dan keyin, "Qayta urinish"). */
  const [attempt, setAttempt] = useState(0);
  /** Oshsa tayyorgarlik qaytadan (sozlamalarda mikrofon yoqilib qaytilganda). */
  const [round, setRound] = useState(0);
  const web = useRef<WebView>(null);
  const phaseRef = useRef<Phase>('starting');
  /** Sahifadagi qo'ng'iroq ketyaptimi (sahifa `status` xabaridan). */
  const active = useRef(false);
  /** 401 dan keyin token bir marta yangilanadi - yana rad etilsa "qayta kiring". */
  const authRetried = useRef(false);
  const closing = useRef(false);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // O'qilayotgan javob ("Tinglash") qo'ng'iroq ovoziga aralashmasin.
  useEffect(() => {
    stopReadAloud();
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const next = await preflight(session);
      if (!alive) return;
      setToken(next.token);
      setPhase(next.phase);
    })();
    return () => {
      alive = false;
    };
  }, [session, round]);

  // Odam gaplashayotganda telefonga tegmaydi - ekran o'chsa ilova fonga o'tib qo'ng'iroq uzilardi.
  useEffect(() => {
    keepScreenOn('live', true);
    return () => keepScreenOn('live', false);
  }, []);

  const endCall = useCallback(() => {
    web.current?.injectJavaScript(END_SCRIPT);
  }, []);

  const close = useCallback(async () => {
    if (closing.current) return;
    closing.current = true;
    if (active.current) {
      endCall();
      await new Promise<void>((resolve) => setTimeout(resolve, END_WAIT_MS));
    }
    if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [endCall]);

  useFocusEffect(
    useCallback(() => {
      const sub = BackHandler.addEventListener('hardwareBackPress', () => {
        if (active.current) endCall();
        else void close();
        return true;
      });
      return () => sub.remove();
    }, [endCall, close]),
  );

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        if (timer) clearTimeout(timer);
        timer = null;
        // Sozlamalarda mikrofon yoqilib qaytildi - davom etamiz.
        if (phaseRef.current === 'denied') {
          void hasMicPermission().then((ok) => {
            if (ok) setRound((n) => n + 1);
          });
        }
        return;
      }
      if (state === 'background' && active.current && !timer) {
        timer = setTimeout(() => {
          timer = null;
          if (active.current) endCall();
        }, BACKGROUND_END_MS);
      }
    });
    return () => {
      sub.remove();
      if (timer) clearTimeout(timer);
    };
  }, [endCall]);

  const onMessage = useCallback(
    (e: WebViewMessageEvent) => {
      const msg = parseLiveMessage(e.nativeEvent.data);
      if (!msg) return;
      switch (msg.type) {
        case 'ready':
          // Token faqat o'z saytimiz so'rasa.
          if (!sameOrigin(e.nativeEvent.url, origin)) return;
          void session
            .getToken()
            .then((fresh) => web.current?.injectJavaScript(tokenScript(origin, fresh)))
            .catch(() => setPhase('auth'));
          return;
        case 'status':
          active.current = ACTIVE_STATUSES.has(msg.status);
          return;
        case 'auth':
          active.current = false;
          if (authRetried.current) {
            setPhase('auth');
            return;
          }
          authRetried.current = true;
          void session
            .refreshToken()
            .then((fresh) => {
              setToken(fresh);
              setAttempt((n) => n + 1);
            })
            .catch(() => setPhase('auth'));
          return;
        case 'close':
          void close();
          return;
      }
    },
    [origin, session, close],
  );

  const retry = useCallback(() => {
    active.current = false;
    setAttempt((n) => n + 1);
    setPhase('ready');
  }, []);

  const failed = useCallback(() => {
    active.current = false;
    setPhase('failed');
  }, []);

  return (
    <View style={[s.root, { backgroundColor: th.bg, paddingTop: insets.top, paddingBottom: insets.bottom }]} testID="live-screen">
      <View style={s.bar}>
        <IconButton icon={X} label={t('nav.live.close')} onPress={() => void close()} testID="live-close" />
      </View>
      <View style={s.body}>
        {phase === 'ready' && token ? (
          <WebView
            key={attempt}
            ref={web}
            testID="live-web"
            source={{ uri: url }}
            originWhitelist={[origin]}
            injectedJavaScriptBeforeContentLoaded={tokenScript(origin, token)}
            onMessage={onMessage}
            javaScriptEnabled
            domStorageEnabled
            mediaPlaybackRequiresUserAction={false}
            allowsInlineMediaPlayback
            mediaCapturePermissionGrantType="grant"
            setSupportMultipleWindows={false}
            applicationNameForUserAgent={`BarnoApp/${appVersion}`}
            overScrollMode="never"
            bounces={false}
            startInLoadingState
            renderLoading={() => (
              <View style={[StyleSheet.absoluteFill, { backgroundColor: th.bg }]}>
                <Loading />
              </View>
            )}
            onError={failed}
            onHttpError={(e) => {
              if (e.nativeEvent.statusCode >= 400) failed();
            }}
            onRenderProcessGone={failed}
            webviewDebuggingEnabled={__DEV__}
            style={{ flex: 1, backgroundColor: th.bg }}
            containerStyle={{ backgroundColor: th.bg }}
          />
        ) : phase === 'denied' ? (
          <EmptyState
            testID="live-denied"
            icon={MicOff}
            title={t('nav.live.micDenied')}
            body={t('nav.live.micDeniedBody')}
            action={{ title: t('nav.live.openSettings'), onPress: () => void Linking.openSettings(), testID: 'live-settings' }}
          />
        ) : phase === 'failed' ? (
          <EmptyState
            testID="live-failed"
            icon={WifiOff}
            title={t('nav.live.failed')}
            body={t('nav.live.failedBody')}
            action={{ title: t('nav.live.retry'), icon: RotateCw, onPress: retry, testID: 'live-retry' }}
          />
        ) : phase === 'auth' ? (
          <EmptyState
            testID="live-auth"
            icon={LogIn}
            title={t('nav.live.auth')}
            body={t('nav.live.authBody')}
            action={{ title: t('nav.live.close'), onPress: () => void close(), testID: 'live-auth-close' }}
          />
        ) : (
          <Loading />
        )}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  bar: { height: 52, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 6 },
  body: { flex: 1 },
});
