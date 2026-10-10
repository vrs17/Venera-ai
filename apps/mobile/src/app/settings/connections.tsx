/**
 * Ulanishlar: HRM/CRM holati (qaysi login bilan, ulanganmi yoki muddati tugaganmi)
 * va "Qayta kirish".
 *
 * Qayta kirish faqat SESSIYANI yangilaydi: navbatdagi (yuklanmagan) yozuvlar saqlanadi
 * va qayta kirgandan keyin yuklash davom etadi. Shuning uchun bu "Chiqish" emas.
 * CRM xatosidagi "Sozlamalar > Ulanishlar" matni shu sahifaga to'g'ri olib keladi.
 */
import { useQuery } from '@tanstack/react-query';
import { Briefcase, CloudOff, Plug, RefreshCw, UsersRound, type LucideIcon } from 'lucide-react-native';
import { useState } from 'react';
import { ActivityIndicator, Alert, RefreshControl, ScrollView } from 'react-native';

import type { ConnectorStatus } from '@/api/chat';
import { useChat } from '@/features/chat/chatStore';
import { useT } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { useServices } from '@/services';
import { EmptyState } from '@/ui/EmptyState';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import type { PillTone } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';

export default function ConnectionsScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const services = useServices();
  // Hub bilan bir xil kalit: hub'da yuklangan holat bu yerda darhol ko'rinadi.
  const q = useQuery({ queryKey: ['connectors'], queryFn: () => services.chat.connectors(), staleTime: 30_000 });
  // Faqat qo'lda tortilganda aylanadi - fon yangilanishida tepada spinner sakramasin.
  const [pulling, setPulling] = useState(false);

  const onRefresh = async () => {
    setPulling(true);
    try {
      await q.refetch();
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
        <ListGroup footer={t('settings.reconnectHint')}>
          {list.map((c) => {
            const st = connPill(t, c);
            return (
              <ListRow
                key={c.id}
                testID={`conn-${c.id}`}
                icon={connIcon(c.id)}
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
    </ScrollView>
  );
}

function connIcon(id: string): LucideIcon {
  if (id === 'hrm') return UsersRound;
  if (id === 'crm') return Briefcase;
  return Plug;
}

function connPill(t: TFn, c: ConnectorStatus): { label: string; tone: PillTone } {
  if (!c.configured) return { label: t('settings.connNotConfigured'), tone: 'neutral' };
  if (c.state === 'connected') return { label: t('settings.connConnected'), tone: 'good' };
  if (c.state === 'expired') return { label: t('settings.connExpired'), tone: 'warn' };
  return { label: t('settings.connDisconnected'), tone: 'bad' };
}
