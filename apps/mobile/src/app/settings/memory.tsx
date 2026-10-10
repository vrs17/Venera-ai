/**
 * "Xotira": Barno foydalanuvchi haqida nimani eslab qolgani (yordamchi 3.3). Mini App
 * `MemorySheet.vue` va web `MemoryDialog` bilan bir xil mantiq, ko'rinishi - ilovaning
 * guruhlangan ro'yxati (Sozlamalar sahifalari kabi):
 *
 *   - band: Barno saqlagan gap, ostida kelib chiqishi va sanasi; o'ngda savat (44 dp);
 *   - savat bosilsa - qatorning O'ZIDA tasdiq ("Barno buni unutsinmi?" Bekor / Unutish):
 *     bitta tasodifiy bosish o'chirmaydi, qaytarish yo'q (yordamchida tiklash yo'li yo'q);
 *   - "Hammasini unutish" - pastdan chiqadigan oynada KUCHLI tasdiq: nechta narsa o'chishi,
 *     suhbatlar qolishi va "Tushundim" belgisisiz tugma o'chiq. RN `Alert` da katakcha yo'q;
 *   - bo'sh holat: Barno nimani eslab qolishi va chatda qanday aytish. Namunalar - xira kursiv
 *     iqtibos, pufakcha EMAS: chatdagi xabarga o'xshasa odam ularni bosardi va hech narsa bo'lmasdi.
 *
 * Har ochilishda serverdan (odam chatda yangisini qo'shgan bo'lishi mumkin). `memory_not_found`
 * (404) - band allaqachon yo'q (chatda "unut" deyilgan): xato emas, ro'yxatdan olinadi.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Brain, Check, CloudOff, Trash } from 'lucide-react-native';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, ActivityIndicator, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { assistantErrorKind, type MemoryItem, type MemoryList } from '@/api/assistant';
import { formatDay, tashkentDayKey } from '@/features/meeting/formatDate';
import {
  assistantErrorText,
  forgetAllHint,
  MEMORY_KEY,
  memoryOriginKey,
  useAssistantApi,
  useMemoryQuery,
} from '@/features/settings/assistant';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { TFn, UiLang } from '@/i18n';
import { Button } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { showToast } from '@/ui/errors';
import { IconButton } from '@/ui/IconButton';
import { IconTile } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme, type Theme } from '@/ui/theme';
import { hit, radius, type as typeScale } from '@/ui/tokens';

export default function MemoryScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const api = useAssistantApi();
  const qc = useQueryClient();
  const uiLang = useSettings((s) => s.uiLang);
  // 0 - har ochilishda yangidan: odam chatda "eslab qol" deb yangisini qo'shgan bo'lishi mumkin.
  const q = useMemoryQuery(0);
  const [pulling, setPulling] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  /** Hozir o'chirilayotgan band (bir vaqtda bittasi - ikki bosish ikki so'rov emas). */
  const [removing, setRemoving] = useState<string | null>(null);
  const [wiping, setWiping] = useState(false);
  /**
   * Oyna ochilgan paytdagi ro'yxat: izohdagi "N ta" odam o'qiyotganda o'zgarmasin (fon yangilanishi)
   * va muvaffaqiyatdan keyin yopilish animatsiyasida "0 ta narsaning hammasini" bo'lib qolmasin.
   */
  const [wipeItems, setWipeItems] = useState<MemoryItem[]>([]);
  const [clearing, setClearing] = useState(false);

  const items = q.data?.items ?? [];

  const onRefresh = async () => {
    setPulling(true);
    try {
      await q.refetch();
    } finally {
      setPulling(false);
    }
  };

  // Hub'dagi "N ta" ham shu keshdan - u ham darhol kamayadi.
  const drop = (id: string) =>
    qc.setQueryData<MemoryList>(MEMORY_KEY, (old) => {
      if (!old) return old;
      const next = old.items.filter((m) => m.id !== id);
      return { items: next, count: next.length };
    });

  const forgotten = async (id: string) => {
    // Sahifa ochilganda boshlangan yuklash hali kelmagan bo'lishi mumkin: eski javob unutilgan
    // bandni ro'yxatga qaytarmasin ("Hammasini unutish" dagi kabi).
    await qc.cancelQueries({ queryKey: MEMORY_KEY });
    drop(id);
    setConfirmId(null);
    showToast(t('set.memory.forgotten'));
  };

  const forget = async (item: MemoryItem) => {
    if (removing || clearing) return;
    setRemoving(item.id);
    try {
      await api.deleteMemoryItem(item.id);
      await forgotten(item.id);
    } catch (err) {
      const kind = assistantErrorKind(err);
      // Allaqachon yo'q (chatda "unut" deyilgan yoki boshqa qurilmada) - natija bir xil.
      if (kind === 'notFound') {
        await forgotten(item.id);
      } else {
        showToast(`${t('set.memory.forgetFailed')}. ${assistantErrorText(t, kind)}`);
      }
    } finally {
      setRemoving(null);
    }
  };

  const forgetAll = async () => {
    if (clearing) return;
    setClearing(true);
    try {
      await api.forgetAllMemory();
      // Fonda kelayotgan eski ro'yxat tozalangan xotirani qaytarib ko'rsatmasin.
      await qc.cancelQueries({ queryKey: MEMORY_KEY });
      qc.setQueryData<MemoryList>(MEMORY_KEY, { items: [], count: 0 });
      setConfirmId(null);
      setWiping(false);
      showToast(t('set.memory.forgotAll'));
    } catch (err) {
      showToast(`${t('set.memory.forgetAllFailed')}. ${assistantErrorText(t, assistantErrorKind(err))}`);
    } finally {
      setClearing(false);
    }
  };

  let body: ReactNode;
  if (!q.data && q.isError) {
    body = (
      <EmptyState
        compact
        testID="memory-error"
        icon={CloudOff}
        tone="warn"
        title={t('set.memory.loadFailed')}
        body={assistantErrorText(t, assistantErrorKind(q.error))}
        action={{ title: t('common.retry'), onPress: () => void q.refetch(), variant: 'secondary', testID: 'memory-retry' }}
      />
    );
  } else if (!q.data) {
    body = <ActivityIndicator testID="memory-loading" color={th.textMuted} style={{ marginVertical: 24 }} />;
  } else if (!items.length) {
    body = <MemoryEmpty t={t} th={th} />;
  } else {
    body = (
      <>
        <ListGroup testID="memory-list" footer={t('set.memory.tip')}>
          {items.map((item) => (
            <MemoryRow
              key={item.id}
              item={item}
              t={t}
              th={th}
              lang={uiLang}
              confirming={confirmId === item.id}
              busy={removing === item.id}
              locked={!!removing || clearing}
              onAsk={() => setConfirmId(item.id)}
              onKeep={() => setConfirmId(null)}
              onForget={() => void forget(item)}
            />
          ))}
        </ListGroup>
        <ListGroup>
          <ListRow
            testID="memory-forget-all"
            icon={Trash}
            title={t('set.memory.forgetAll')}
            destructive
            disabled={!!removing}
            onPress={() => {
              setWipeItems(items);
              setWiping(true);
            }}
          />
        </ListGroup>
      </>
    );
  }

  return (
    <>
      <ScrollView
        testID="memory-screen"
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
        <Text style={[typeScale.sub, s.lead, { color: th.textMuted }]}>{t('set.memory.lead')}</Text>
        {body}
      </ScrollView>
      <ForgetAllSheet
        visible={wiping}
        items={wipeItems}
        busy={clearing}
        t={t}
        th={th}
        bottom={insets.bottom}
        onCancel={() => !clearing && setWiping(false)}
        onConfirm={() => void forgetAll()}
      />
    </>
  );
}

function dateOf(item: MemoryItem, lang: UiLang): string {
  const at = item.updated_at ?? item.created_at;
  const key = at ? tashkentDayKey(at) : '';
  if (!key) return '';
  return formatDay(key, lang, { withYear: key.slice(0, 4) !== tashkentDayKey(Date.now()).slice(0, 4) });
}

function MemoryRow(p: {
  item: MemoryItem;
  t: TFn;
  th: Theme;
  lang: UiLang;
  confirming: boolean;
  busy: boolean;
  locked: boolean;
  onAsk: () => void;
  onKeep: () => void;
  onForget: () => void;
}) {
  const { item, t, th } = p;
  const date = dateOf(item, p.lang);
  const questionRef = useRef<Text>(null);
  const trashRef = useRef<View>(null);
  const backToTrash = useRef(false);

  // TalkBack: savat bosilganda u ekrandan yo'qoladi va fokus "osilib" qoladi, yangi tasdiq esa
  // o'qilmaydi (`alert` roli Android'da hech narsa aytmaydi). Shuning uchun fokus SAVOLGA o'tadi -
  // "Barno buni unutsinmi?" o'qiladi, keyingi surishlarda izoh va "Bekor qilish". Bekor qilinsa - savatga
  // qaytadi. Unutilganda qator o'zi yo'qoladi, xabar (toast) aytiladi.
  useEffect(() => {
    const target = p.confirming ? questionRef.current : backToTrash.current ? trashRef.current : null;
    backToTrash.current = false;
    if (!target) return;
    // Yangi ko'ringan view hali joylashmagan bo'lishi mumkin - fokus bir zumdan keyin.
    const id = setTimeout(() => AccessibilityInfo.sendAccessibilityEvent(target, 'focus'), A11Y_FOCUS_DELAY_MS);
    return () => clearTimeout(id);
  }, [p.confirming]);

  const keep = () => {
    backToTrash.current = true;
    p.onKeep();
  };

  return (
    // "Band" holati qatorda emas (View accessible emas - TalkBack uni o'qimaydi): tugma matni
    // "Unutilmoqda..." ga o'zgaradi va o'chadi - shu aytiladi.
    <View testID={`memory-${item.id}`} style={[s.row, { backgroundColor: th.surfaceAlt }]}>
      <View style={s.rowTop}>
        <View style={s.rowText}>
          <Text selectable style={[typeScale.body, { color: p.busy ? th.textMuted : th.text }]}>
            {item.text}
          </Text>
          <Text style={[typeScale.caption, { color: th.textMuted }]}>{date ? `${t(memoryOriginKey(item))} · ${date}` : t(memoryOriginKey(item))}</Text>
        </View>
        {p.confirming ? null : (
          <IconButton
            ref={trashRef}
            testID={`memory-forget-${item.id}`}
            icon={Trash}
            size={18}
            color={th.textMuted}
            label={t('set.memory.forgetA11y', { text: item.text })}
            disabled={p.locked}
            onPress={p.onAsk}
          />
        )}
      </View>
      {p.confirming ? (
        // Tasdiq qatorning O'ZIDA: qaysi band unutilayotgani ko'z oldida turadi.
        <View testID={`memory-confirm-${item.id}`} accessibilityRole="alert" style={[s.confirm, { backgroundColor: th.tones.bad.bg }]}>
          <Text ref={questionRef} testID={`memory-confirm-q-${item.id}`} style={[typeScale.label, { color: th.tones.bad.fg }]}>
            {t('set.memory.forgetConfirm')}
          </Text>
          <Text style={[typeScale.caption, { color: th.textSoft }]}>{t('set.memory.forgetConfirmHint')}</Text>
          <View style={s.confirmActions}>
            <Button
              small
              testID={`memory-keep-${item.id}`}
              variant="secondary"
              title={t('common.cancel')}
              disabled={p.busy}
              onPress={keep}
              style={s.flex}
            />
            <Button
              small
              testID={`memory-forget-yes-${item.id}`}
              variant="danger"
              title={p.busy ? t('set.memory.forgetting') : t('set.memory.forget')}
              disabled={p.busy}
              onPress={p.onForget}
              style={s.flex}
            />
          </View>
        </View>
      ) : null}
    </View>
  );
}

function MemoryEmpty({ t, th }: { t: TFn; th: Theme }) {
  return (
    <View testID="memory-empty" style={[s.empty, { backgroundColor: th.surfaceAlt }]}>
      <IconTile icon={Brain} tone="raised" size="lg" />
      <Text style={[typeScale.headline, s.center, { color: th.text }]}>{t('set.memory.emptyTitle')}</Text>
      <Text style={[typeScale.sub, s.center, { color: th.textSoft }]}>{t('set.memory.emptyBody')}</Text>
      {/* Namuna - fonsiz, kursiv, xira iqtibos: tugma yoki xabar pufakchasiga o'xshamasin. */}
      <Text testID="memory-example" style={[typeScale.sub, s.center, s.example, { color: th.textMuted }]}>
        {t('set.memory.exampleRemember')}
      </Text>
      <Text testID="memory-example" style={[typeScale.sub, s.center, s.example, { color: th.textMuted }]}>
        {t('set.memory.exampleForget')}
      </Text>
    </View>
  );
}

/** "Hammasini unutish" - kuchli tasdiq: son, suhbatlar qolishi va "Tushundim" katakchasi. */
function ForgetAllSheet(p: {
  visible: boolean;
  items: MemoryItem[];
  busy: boolean;
  t: TFn;
  th: Theme;
  bottom: number;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t, th } = p;
  const [ack, setAck] = useState(false);
  // Har ochilishda katakcha qaytadan bo'sh: oldingi "Tushundim" keyingi safar o'tib ketmasin.
  const [wasVisible, setWasVisible] = useState(p.visible);
  if (wasVisible !== p.visible) {
    setWasVisible(p.visible);
    if (p.visible) setAck(false);
  }
  return (
    <Modal visible={p.visible} transparent animationType="slide" statusBarTranslucent onRequestClose={p.onCancel}>
      <View style={s.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={p.onCancel} accessibilityLabel={t('common.close')} />
        <View testID="memory-wipe" accessibilityViewIsModal style={[s.sheet, { backgroundColor: th.surface, paddingBottom: Math.max(p.bottom, 12) + 8 }]}>
          <View style={[s.grabber, { backgroundColor: th.borderStrong }]} />
          <Text accessibilityRole="header" style={[typeScale.title, { color: th.text }]}>
            {t('set.memory.forgetAllTitle')}
          </Text>
          <Text testID="memory-wipe-hint" style={[typeScale.sub, { color: th.textSoft }]}>
            {forgetAllHint(p.items, t)}
          </Text>
          <Pressable
            testID="memory-wipe-ack"
            accessibilityRole="checkbox"
            accessibilityState={{ checked: ack, disabled: p.busy }}
            disabled={p.busy}
            onPress={() => setAck((v) => !v)}
            style={[s.ack, { backgroundColor: th.tones.bad.bg }]}>
            <View style={[s.box, { borderColor: ack ? th.danger : th.borderStrong, backgroundColor: ack ? th.danger : th.surface }]}>
              {ack ? <Check size={14} color="#FFFFFF" strokeWidth={3} /> : null}
            </View>
            <Text style={[typeScale.sub, s.flex, { color: th.text }]}>{t('set.memory.forgetAllAck')}</Text>
          </Pressable>
          <Button
            testID="memory-wipe-yes"
            variant="danger"
            title={t('set.memory.forgetAllYes')}
            loading={p.busy}
            disabled={!ack}
            // Tugma o'chiq bo'lsa ham bu yerda yana tekshiriladi (Mini App kabi): qaytarib bo'lmaydigan
            // amal faqat "Tushundim" belgilanganda.
            onPress={() => {
              if (ack && !p.busy) p.onConfirm();
            }}
          />
          <Button testID="memory-wipe-cancel" variant="secondary" title={t('common.cancel')} disabled={p.busy} onPress={p.onCancel} />
        </View>
      </View>
    </Modal>
  );
}

/** Tasdiq ko'ringach TalkBack fokusini ko'chirishdan oldingi kutish (view joylashib olsin). */
const A11Y_FOCUS_DELAY_MS = 120;

const s = StyleSheet.create({
  lead: { paddingHorizontal: 4, marginBottom: 16 },
  row: { paddingLeft: 16, paddingRight: 6, paddingVertical: 12, gap: 8 },
  rowTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  rowText: { flex: 1, minWidth: 0, gap: 4, paddingTop: 2 },
  confirm: { marginRight: 10, padding: 12, borderRadius: radius.md, gap: 4 },
  confirmActions: { flexDirection: 'row', gap: 8, marginTop: 8 },
  flex: { flex: 1 },
  empty: { alignItems: 'center', gap: 10, padding: 24, borderRadius: radius.lg },
  center: { textAlign: 'center', maxWidth: 340 },
  example: { fontStyle: 'italic' },
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: { borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingHorizontal: 20, paddingTop: 8, gap: 12 },
  grabber: { alignSelf: 'center', width: 36, height: 4, borderRadius: 2, marginBottom: 4 },
  ack: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: hit.min, padding: 12, borderRadius: radius.md },
  box: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
});
