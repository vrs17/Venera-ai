/**
 * Vazifalar tabi (spec 7.4): mas'ul bo'yicha guruhlangan; belgilash,
 * tahrirlash, qo'shish, olib tashlash. Iqtibos va dalil chipi ko'rinadi.
 * "tekshiring" - AI egasi yoki muddatini aniq bilmagan band.
 * Har vazifa ostida - "CRMga qo'shish" (Barno taklifi, tasdiqlash bilan; `features/crm`).
 */
import { useMemo, useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { ActionItem, Lang, Meeting, Speaker } from '@/api/types';
import { CrmPanel } from '@/features/crm/CrmPanel';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { Banner, Button, Card, Checkbox, Chip, EvidenceChip, Field, Loading, Muted, styles as ui } from '@/ui/components';
import { PickerModal, PromptModal } from '@/ui/modals';
import { useTheme } from '@/ui/theme';

import { formatDue } from './formatDate';
import { useActionItems, useMeetingMutations } from './queries';
import { speakerLabel } from './renderTokens';

export function ownerLabel(item: Pick<ActionItem, 'owner'>, speakers: Speaker[], lang: Lang, noOwner: string, team: string): string {
  if (item.owner.speaker) return speakerLabel(item.owner.speaker, speakers, lang);
  if (item.owner.name) return item.owner.name;
  if (item.owner.kind === 'team') return team;
  return noOwner;
}

const STATUS_ORDER = { open: 0, done: 1, dismissed: 2 } as const;

/** Mas'ul bo'yicha guruhlar; guruh ichida: ochiq -> bajarilgan -> olib tashlangan, keyin muddat. */
export function groupByOwner(items: ActionItem[], labelOf: (i: ActionItem) => string): { owner: string; items: ActionItem[] }[] {
  const groups = new Map<string, ActionItem[]>();
  for (const it of items) {
    const k = labelOf(it);
    const arr = groups.get(k) ?? [];
    arr.push(it);
    groups.set(k, arr);
  }
  const sortKey = (i: ActionItem) => `${STATUS_ORDER[i.status]}|${i.due.date ?? '9999'}|${i.id}`;
  return [...groups.entries()]
    .map(([owner, arr]) => ({ owner, items: arr.sort((a, b) => sortKey(a).localeCompare(sortKey(b))) }))
    .sort((a, b) => {
      const ao = a.items.some((i) => i.status === 'open') ? 0 : 1;
      const bo = b.items.some((i) => i.status === 'open') ? 0 : 1;
      return ao - bo || a.owner.localeCompare(b.owner);
    });
}

export function ActionItemsView({ meeting, speakers, onSeek }: { meeting: Meeting; speakers: Speaker[]; onSeek?: (t: number) => void }) {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const q = useActionItems(meeting.id, meeting.transcript.available);
  const muts = useMeetingMutations(meeting.id);
  const [adding, setAdding] = useState(false);
  const [task, setTask] = useState('');
  const [owner, setOwner] = useState('');
  const [due, setDue] = useState('');
  const [menu, setMenu] = useState<ActionItem | null>(null);
  const [editing, setEditing] = useState<ActionItem | null>(null);

  const labelOf = (i: ActionItem) => ownerLabel(i, speakers, lang, t('ai.noOwnerGroup'), t('sum.team'));
  const groups = useMemo(() => groupByOwner(q.data?.items ?? [], labelOf), [q.data, speakers, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!meeting.transcript.available) return <Banner tone="info" text={t('detail.processing')} />;
  if (q.isLoading) return <Loading />;

  const submit = () => {
    const dueDate = /^\d{4}-\d{2}-\d{2}$/.test(due.trim()) ? due.trim() : null;
    muts.addActionItem.mutate({ task: task.trim(), ownerName: owner.trim() || null, dueDate });
    setTask('');
    setOwner('');
    setDue('');
    setAdding(false);
  };

  return (
    <View>
      {groups.length === 0 ? <Muted>{t('ai.empty')}</Muted> : null}
      {groups.map((g) => (
        <Card key={g.owner}>
          <Text style={[s.groupTitle, { color: th.text }]}>{g.owner}</Text>
          {g.items.map((it) => (
            <ActionRow
              key={it.id}
              item={it}
              lang={lang}
              onToggle={() => muts.patchActionItem.mutate({ itemId: it.id, body: { status: it.status === 'done' ? 'open' : 'done' } })}
              onLongPress={() => setMenu(it)}
              onSeek={onSeek}
              footer={<CrmPanel item={it} speakers={speakers} />}
            />
          ))}
        </Card>
      ))}

      {adding ? (
        <Card>
          <Field label={t('ai.task')} value={task} onChangeText={setTask} testID="ai-task" />
          <Field label={t('ai.owner')} value={owner} onChangeText={setOwner} />
          <Field label={t('ai.due')} value={due} onChangeText={setDue} placeholder="2026-10-15" />
          <View style={ui.row}>
            <Button small variant="ghost" title={t('common.cancel')} onPress={() => setAdding(false)} />
            <Button small title={t('common.add')} disabled={!task.trim()} onPress={submit} style={{ marginLeft: 8 }} testID="ai-submit" />
          </View>
        </Card>
      ) : (
        <Button variant="secondary" title={t('ai.add')} onPress={() => setAdding(true)} testID="ai-add" />
      )}

      <PickerModal
        visible={!!menu}
        title={menu?.task ?? ''}
        options={[
          { value: 'edit' as const, label: t('common.edit') },
          menu?.status === 'dismissed'
            ? { value: 'reopen' as const, label: t('ai.reopen') }
            : { value: 'dismiss' as const, label: t('ai.dismiss'), destructive: true },
        ]}
        onCancel={() => setMenu(null)}
        onPick={(a) => {
          const it = menu;
          setMenu(null);
          if (!it) return;
          if (a === 'edit') setEditing(it);
          if (a === 'dismiss') muts.patchActionItem.mutate({ itemId: it.id, body: { status: 'dismissed' } });
          if (a === 'reopen') muts.patchActionItem.mutate({ itemId: it.id, body: { status: 'open' } });
        }}
      />
      <PromptModal
        visible={!!editing}
        title={t('ai.task')}
        initial={editing?.task}
        multiline
        maxLength={500}
        onCancel={() => setEditing(null)}
        onSubmit={(text) => {
          if (editing && text !== editing.task) muts.patchActionItem.mutate({ itemId: editing.id, body: { task: text } });
          setEditing(null);
        }}
      />
    </View>
  );
}

export function ActionRow({
  item,
  lang,
  onToggle,
  onLongPress,
  onSeek,
  subtitle,
  footer,
}: {
  item: ActionItem;
  lang: Lang;
  onToggle: () => void;
  onLongPress?: () => void;
  onSeek?: (t: number) => void;
  subtitle?: string;
  /** Vazifa ostidagi qo'shimcha blok (CRM). */
  footer?: ReactNode;
}) {
  const th = useTheme();
  const t = useT();
  const due = formatDue(item.due.date, item.due.time, item.due.raw, lang);
  const done = item.status === 'done';
  const dismissed = item.status === 'dismissed';
  // `footer` (CRM bloki) bosiladigan qatordan TASHQARIDA va butun kenglikda: TalkBack kartaning
  // matni va tugmalariga alohida-alohida yetadi, kartani bosib turish esa qator menyusini ochmaydi.
  return (
    <View style={[s.item, { borderColor: th.border }]}>
      <Pressable onLongPress={onLongPress} style={[s.row, { opacity: dismissed ? 0.5 : 1 }]}>
        <Checkbox testID={`ai-check-${item.id}`} checked={done} onPress={onToggle} label={item.task} />
        <View style={{ flex: 1, marginLeft: 10 }}>
          <Text style={[s.task, { color: th.text, textDecorationLine: done || dismissed ? 'line-through' : 'none' }]}>{item.task}</Text>
          {subtitle ? <Text style={[s.meta, { color: th.textMuted }]}>{subtitle}</Text> : null}
          {due ? <Text style={[s.meta, { color: th.textMuted }]}>{t('sum.due', { due })}</Text> : null}
          {item.quote ? <Text style={[s.quote, { color: th.textMuted }]}>“{item.quote}”</Text> : null}
          <View style={ui.wrap}>
            {item.priority === 'high' ? <Chip label={t('sum.priority.high')} tone="bad" /> : null}
            {item.needsConfirmation ? <Chip label={t('sum.check')} tone="warn" /> : null}
            {dismissed ? <Chip label={t('ai.dismissed')} /> : null}
            <EvidenceChip start={item.start} onSeek={onSeek} />
          </View>
        </View>
      </Pressable>
      {footer}
    </View>
  );
}

const s = StyleSheet.create({
  groupTitle: { fontSize: 15, fontWeight: '700', marginBottom: 4 },
  item: { paddingVertical: 10, borderTopWidth: StyleSheet.hairlineWidth },
  row: { flexDirection: 'row', alignItems: 'flex-start' },
  task: { fontSize: 15, lineHeight: 21 },
  meta: { fontSize: 13, marginTop: 2 },
  quote: { fontSize: 13, fontStyle: 'italic', marginTop: 2 },
});
