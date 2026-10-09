/**
 * Mening vazifalarim - barcha yig'ilishlar bo'yicha (spec 3.2 #25, 7.4).
 * Plaud buni qila olmaydi: vazifalar yig'ilishdan yig'ilishga kuzatiladi.
 * Shu yerdan ham vazifani CRM ga yuborish mumkin (taklif + tasdiqlash, `features/crm`).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { GlobalActionItem } from '@/api/types';
import { CrmPanel } from '@/features/crm/CrmPanel';
import { ActionRow, ownerLabel } from '@/features/meeting/ActionItemsView';
import { formatDateTime } from '@/features/meeting/formatDate';
import { qk } from '@/features/meeting/queries';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Card, Loading, Muted, Segmented } from '@/ui/components';
import { useTheme } from '@/ui/theme';

type Filter = 'open' | 'done' | 'all';

/** Yig'ilish bo'yicha guruhlash (yangi yig'ilish yuqorida). */
export function groupByMeeting(items: GlobalActionItem[]): { meetingId: string; title: string; recordedAt: string | null; items: GlobalActionItem[] }[] {
  const map = new Map<string, { meetingId: string; title: string; recordedAt: string | null; items: GlobalActionItem[] }>();
  for (const it of items) {
    const g = map.get(it.meetingId) ?? { meetingId: it.meetingId, title: it.meetingTitle, recordedAt: it.recordedAt ?? null, items: [] };
    g.items.push(it);
    map.set(it.meetingId, g);
  }
  // Server `recordedAt` ni null berishi mumkin (MyActionItem: str | None) - bunday guruh oxirida.
  return [...map.values()].sort((a, b) => (b.recordedAt ?? '').localeCompare(a.recordedAt ?? ''));
}

export default function MyActionItemsScreen() {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const { meetings } = useServices();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>('open');
  const q = useQuery({ queryKey: qk.myItems(filter), queryFn: () => meetings.myActionItems(filter, 100) });
  const toggle = useMutation({
    mutationFn: (it: GlobalActionItem) => meetings.patchActionItem(it.meetingId, it.id, { status: it.status === 'done' ? 'open' : 'done' }),
    onSettled: (_d, _e, it) => {
      void qc.invalidateQueries({ queryKey: ['action-items'] });
      if (it) void qc.invalidateQueries({ queryKey: ['meetings', it.meetingId] });
    },
  });
  const groups = useMemo(() => groupByMeeting(q.data?.items ?? []), [q.data]);

  return (
    <ScrollView
      contentContainerStyle={{ padding: 12, paddingBottom: 48 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => void q.refetch()} />}>
      <Segmented
        options={[
          { value: 'open', label: t('ai.filter.open') },
          { value: 'done', label: t('ai.filter.done') },
          { value: 'all', label: t('ai.filter.all') },
        ]}
        value={filter}
        onChange={setFilter}
      />
      <View style={{ height: 10 }} />
      {q.isLoading ? <Loading /> : null}
      {!q.isLoading && groups.length === 0 ? <Muted>{t('ai.myEmpty')}</Muted> : null}
      {groups.map((g) => (
        <Card key={g.meetingId}>
          <Pressable onPress={() => router.push(`/meeting/${g.meetingId}`)}>
            <Text style={[s.title, { color: th.text }]}>{g.title}</Text>
            {g.recordedAt ? <Muted>{formatDateTime(g.recordedAt, lang)}</Muted> : null}
          </Pressable>
          {g.items.map((it) => (
            <ActionRow
              key={it.id}
              item={it}
              lang={lang}
              subtitle={ownerLabel(it, [], lang, t('ai.noOwnerGroup'), t('sum.team'))}
              onToggle={() => toggle.mutate(it)}
              onLongPress={() => router.push(`/meeting/${it.meetingId}`)}
              footer={<CrmPanel item={it} />}
            />
          ))}
        </Card>
      ))}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  title: { fontSize: 16, fontWeight: '700' },
});
