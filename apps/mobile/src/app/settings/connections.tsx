/**
 * Ulanishlar: HRM/CRM holati (qaysi login bilan, ulanganmi yoki muddati tugaganmi),
 * "Qayta kirish" va "Manbalar" - Barno javob berishda foydalanadigan 7 platforma va har
 * birining kaliti (yordamchi 3.3; Mini App `SettingsSheet.vue` bilan bir xil qoida).
 *
 * Qayta kirish faqat SESSIYANI yangilaydi: navbatdagi (yuklanmagan) yozuvlar saqlanadi
 * va qayta kirgandan keyin yuklash davom etadi. Shuning uchun bu "Chiqish" emas.
 * CRM xatosidagi "Sozlamalar > Ulanishlar" matni shu sahifaga to'g'ri olib keladi.
 *
 * Manbalar: izoh kartadan OLDIN (avval nima ekanini bilib, keyin kalitni ko'radi). Kalit
 * optimistik - darhol o'zgaradi, server rad etsa qaytadi va xabar chiqadi. HRM/CRM yoqiq,
 * lekin Barno hisobdan foydalana olmasa - qator ostida ogohlantirish (`loginIssue`);
 * "Chatda ishlatish" o'chiq bo'lsa - "Yoqish". Platformani yoqish token kalitini ham yoqadi.
 */
import { useQuery } from '@tanstack/react-query';
import { CircleAlert, CloudOff, Plug, RefreshCw } from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { assistantErrorKind, type Platform } from '@/api/assistant';
import type { ConnectorStatus } from '@/api/chat';
import { useChat } from '@/features/chat/chatStore';
import { loginIssue, orderPlatforms, platformIcon, platformName, platformPurpose, type LoginIssue } from '@/features/chat/platforms';
import { assistantErrorText, CONNECTORS_KEY, usePlatformsQuery, usePlatformToggle } from '@/features/settings/assistant';
import { useT } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { useServices } from '@/services';
import { Button } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { showToast } from '@/ui/errors';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import type { PillTone } from '@/ui/StatusPill';
import { useTheme, type Theme } from '@/ui/theme';
import { hit, iconSize, stroke, type as typeScale } from '@/ui/tokens';

export default function ConnectionsScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const services = useServices();
  // Hub bilan bir xil kalit: hub'da yuklangan holat bu yerda darhol ko'rinadi.
  const q = useQuery({ queryKey: CONNECTORS_KEY, queryFn: () => services.chat.connectors(), staleTime: 30_000 });
  const platforms = usePlatformsQuery();
  // Faqat qo'lda tortilganda aylanadi - fon yangilanishida tepada spinner sakramasin.
  const [pulling, setPulling] = useState(false);

  const onRefresh = async () => {
    setPulling(true);
    try {
      await Promise.all([q.refetch(), platforms.refetch()]);
    } finally {
      setPulling(false);
    }
  };

  const reconnect = () =>
    Alert.alert(t('settings.reconnect'), t('settings.reconnectHint'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('settings.reconnect'),
        onPress: () => {
          useChat.getState().abort();
          // Navbat (yuklanmagan yozuvlar) SAQLANADI - faqat sessiya; qayta kirganda davom etadi.
          void services.session.logout();
        },
      },
    ]);

  const list = q.data?.connectors ?? [];

  return (
    <ScrollView
      style={{ backgroundColor: th.bg }}
      contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}
      refreshControl={
        <RefreshControl
          refreshing={pulling}
          onRefresh={() => void onRefresh()}
          colors={[th.brand]}
          tintColor={th.textMuted}
          progressBackgroundColor={th.surface}
        />
      }>
      {q.isLoading ? (
        <ActivityIndicator testID="connections-loading" color={th.textMuted} style={{ marginVertical: 24 }} />
      ) : !q.data && q.isError ? (
        <EmptyState
          compact
          testID="connections-error"
          icon={CloudOff}
          tone="warn"
          title={t('set.connLoadFailed')}
          action={{ title: t('common.retry'), onPress: () => void q.refetch(), variant: 'secondary', testID: 'connections-retry' }}
        />
      ) : list.length ? (
        // Sarlavha: sahifada endi ikki bo'lim - hisoblar (login) va manbalar (kalitlar).
        <ListGroup header={t('set.platforms.accounts')} footer={t('settings.reconnectHint')}>
          {list.map((c) => {
            const st = connPill(t, c);
            return (
              <ListRow
                key={c.id}
                testID={`conn-${c.id}`}
                // Belgi "Manbalar"dagi bilan BIR XIL (`platformIcon`): bitta sahifada HRM ikki xil
                // belgida chiqsa, odam ularni ikki xil narsa deb o'ylaydi.
                icon={platformIcon(c.id)}
                title={c.label || c.id.toUpperCase()}
                subtitle={c.login ? t('settings.connAs', { login: c.login }) : null}
                right={{ kind: 'pill', label: st.label, tone: st.tone, testID: `conn-${c.id}-status` }}
              />
            );
          })}
        </ListGroup>
      ) : (
        <EmptyState compact testID="connections-empty" icon={Plug} title={t('set.connNone')} />
      )}

      <ListGroup>
        <ListRow testID="settings-reconnect" icon={RefreshCw} title={t('settings.reconnect')} right={{ kind: 'none' }} onPress={reconnect} />
      </ListGroup>

      <PlatformsSection t={t} th={th} query={platforms} connectors={list} />
    </ScrollView>
  );
}

/** "Manbalar": izoh, keyin 7 platforma kaliti (yoki yuklanish / xato / bo'sh holati). */
function PlatformsSection({
  t,
  th,
  query,
  connectors,
}: {
  t: TFn;
  th: Theme;
  query: ReturnType<typeof usePlatformsQuery>;
  connectors: ConnectorStatus[];
}) {
  const nameOf = (p: Platform) => platformName(p.id, t, p.name);
  const { pending, enabling, toggle, enableForChat } = usePlatformToggle({
    // `chat` - platforma kaliti SAQLANDI (yoqiq turibdi), faqat "Chatda ishlatish" yoqilmadi:
    // "o'zgartirib bo'lmadi" desak, yoqiq kalitga qarab odam nima bo'lganini tushunmaydi.
    onError: (p, what) =>
      showToast(t(what === 'chat' ? 'set.platforms.chatFailed' : 'set.platforms.toggleFailed', { name: nameOf(p) })),
  });
  const items = query.data ? orderPlatforms(query.data) : null;

  const turnOn = async (p: Platform) => {
    if (!(await enableForChat(p.id))) showToast(t('set.platforms.toggleFailed', { name: nameOf(p) }));
  };

  let content: ReactNode;
  if (items && items.length) {
    content = items.map((p) => {
      const purpose = platformPurpose(p.id, t, p.description);
      // "Mavjud emas" OLDINDA: kalit nega kulrang ekanini odam birinchi o'qiydi (oxirida bo'lsa
      // uzun izoh ortida qolib ketardi).
      const desc = p.available ? purpose : [t('set.platforms.unavailable'), purpose].filter(Boolean).join(' · ');
      const issue: LoginIssue = p.available ? loginIssue(p, connectors.find((c) => String(c.id) === p.id)) : null;
      const busy = pending.has(p.id);
      return (
        // Qator va (bo'lsa) ogohlantirish BITTA element: guruhdagi ingichka chiziq ular orasida emas.
        <View key={p.id} testID={`platform-${p.id}`} style={{ backgroundColor: th.surfaceAlt }}>
          <ListRow
            testID={`platform-${p.id}-row`}
            icon={platformIcon(p.id)}
            title={nameOf(p)}
            subtitle={desc || null}
            subtitleLines={3}
            disabled={!p.available}
            accessibilityLabel={desc ? `${nameOf(p)}. ${desc}` : nameOf(p)}
            right={{
              kind: 'switch',
              value: p.available && p.user_enabled,
              onChange: () => void toggle(p),
              disabled: !p.available || busy,
              testID: `platform-${p.id}-switch`,
            }}
          />
          {issue ? (
            <View testID={`platform-${p.id}-issue`} style={s.issue}>
              <CircleAlert size={iconSize.xs} color={th.tones.warn.fg} strokeWidth={stroke.small} />
              <Text style={[typeScale.caption, s.issueText, { color: th.tones.warn.fg }]}>
                {issue === 'offForChat' ? t('set.platforms.offForChat') : t('set.platforms.needsLogin')}
              </Text>
              {issue === 'offForChat' ? (
                <Pressable
                  testID={`platform-${p.id}-turn-on`}
                  accessibilityRole="button"
                  // TalkBack faqat "Yoqish" desa - qaysi platforma ekani noma'lum (HRM va CRM yonma-yon).
                  accessibilityLabel={`${nameOf(p)}: ${t('set.platforms.turnOn')}`}
                  accessibilityState={{ disabled: enabling === p.id }}
                  disabled={enabling === p.id}
                  hitSlop={8}
                  onPress={() => void turnOn(p)}
                  style={({ pressed }) => [s.fix, { opacity: enabling === p.id ? 0.5 : pressed ? 0.6 : 1 }]}>
                  <Text style={[typeScale.label, s.fixText, { color: th.text }]}>{t('set.platforms.turnOn')}</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}
        </View>
      );
    });
  } else if (items) {
    // Javob keldi, lekin ro'yxat bo'sh - xato emas, oddiy izoh.
    content = <ListRow testID="platforms-empty" title={t('set.platforms.empty')} />;
  } else if (query.isError) {
    content = (
      <ListRow
        testID="platforms-error"
        icon={CloudOff}
        title={t('set.platforms.loadFailed')}
        subtitle={assistantErrorText(t, assistantErrorKind(query.error))}
        right={{
          kind: 'node',
          node: <Button small variant="ghost" testID="platforms-retry" title={t('common.retry')} onPress={() => void query.refetch()} />,
        }}
      />
    );
  } else {
    content = (
      <View style={[s.loading, { backgroundColor: th.surfaceAlt }]}>
        <ActivityIndicator testID="platforms-loading" color={th.textMuted} />
      </View>
    );
  }

  return (
    // Tashqi View'ga a11y nomi YO'Q: sarlavha matni o'zi o'qiladi, nom qo'shilsa TalkBack ikki marta to'xtardi.
    <View testID="platforms">
      <Text accessibilityRole="header" style={[typeScale.label, s.header, { color: th.textMuted }]}>
        {t('set.platforms.title')}
      </Text>
      <Text style={[typeScale.caption, s.lead, { color: th.textMuted }]}>{t('set.platforms.lead')}</Text>
      <ListGroup>{content}</ListGroup>
    </View>
  );
}

function connPill(t: TFn, c: ConnectorStatus): { label: string; tone: PillTone } {
  if (!c.configured) return { label: t('settings.connNotConfigured'), tone: 'neutral' };
  // Ulangan, lekin "Chatda ishlatish" o'chiq - Barno bu hisobdan foydalanmaydi: yashil "Ulangan"
  // chalg'itardi (Mini App bilan bir xil).
  if (c.state === 'connected' && !c.enabled) return { label: t('set.platforms.offForChat'), tone: 'warn' };
  if (c.state === 'connected') return { label: t('settings.connConnected'), tone: 'good' };
  if (c.state === 'expired') return { label: t('settings.connExpired'), tone: 'warn' };
  return { label: t('settings.connDisconnected'), tone: 'bad' };
}

const s = StyleSheet.create({
  header: { paddingHorizontal: 4, marginBottom: 4 },
  lead: { paddingHorizontal: 4, marginBottom: 8 },
  // Belgi (22) + oraliq (14) + chekka (16): ogohlantirish kalit nomi bilan bir chiziqda.
  issue: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, paddingLeft: 52, paddingRight: 16, paddingBottom: 12, marginTop: -4 },
  issueText: { flexShrink: 1 },
  fix: { minHeight: hit.min - 12, justifyContent: 'center', paddingHorizontal: 4 },
  fixText: { textDecorationLine: 'underline' },
  loading: { paddingVertical: 20, alignItems: 'center' },
});
