/**
 * "Tez yozish": ilovani ochmasdan yozishni boshlash usullari - har usul alohida karta
 * (belgi + nom + bir qatorli maqsad + holat), sozlash qadamlari esa "Qanday sozlash"
 * ichida YOPIQ turadi.
 *
 * NIMA UCHUN kartalar: eski sahifada hamma usul bitta uzun matn edi (raqamlangan qadamlar,
 * bannerlar) - egasi "hamma joyda matn" dedi. Endi bir qarashda: qaysi usul bor, qaysi
 * yoqilgan, keyingi qadam qaysi tugma.
 *
 * Xatti-harakat eskisi bilan bir xil: launcher switch'i (native holat kechiksa ham tanlov
 * ko'rinadi), plitka so'rovi natijasi. Native modul yo'q bo'lsa (iOS, Jest) faqat ilova
 * yorlig'i ishlaydi - qolganlari "Bu telefonda yo'q" deydi va tugmalari o'chadi.
 *
 * "Ovoz tugmasi bilan yozish" yo'q (ega qarori, 2026-11-09): u "Maxsus imkoniyatlar" xizmati
 * edi va Google Play Protect sideload o'rnatishni to'sdi. Qaytarilmasin - `playProtect.test.ts`.
 */
import { AppWindow, LayoutGrid, PanelTop, Plus, Smartphone, type LucideIcon } from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';

import { isLauncherEnabled, requestAddTile, setLauncherEnabled, type AddTileResult } from '@/features/entry/nativeEntry';
import { useQuickState } from '@/features/settings/quickMethods';
import { useT } from '@/features/settings/settingsStore';
import type { TKey } from '@/i18n';
import { Collapsible, StepList } from '@/ui/Collapsible';
import { Button } from '@/ui/components';
import { useSafeInsets } from '@/ui/insets';
import { StatusPill, type PillTone } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';
import { iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

const TILE_PILL: Record<AddTileResult, { key: TKey; tone: PillTone }> = {
  added: { key: 'settings.tile.added', tone: 'good' },
  already: { key: 'settings.tile.already', tone: 'good' },
  denied: { key: 'settings.tile.denied', tone: 'warn' },
  unsupported: { key: 'set.m.tileUnsupported', tone: 'warn' },
};

export default function QuickRecordScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const quick = useQuickState();
  const { available } = quick;
  const [tile, setTile] = useState<AddTileResult | null>(null);
  const [tileHelp, setTileHelp] = useState(false);

  const unavailable = <StatusPill label={t('set.unavailable')} style={s.pill} />;

  const addTile = async () => {
    const r = await requestAddTile();
    setTile(r);
    // Tizim so'rovni qo'llamasa qo'lda qo'shish yo'li darhol ochiq tursin - qidirtirmaylik.
    if (r === 'unsupported') setTileHelp(true);
  };

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}>
      <Text style={[typeScale.sub, s.intro, { color: th.textMuted }]}>{t('set.quickIntro')}</Text>

      <MethodCard
        testID="quick-launcher"
        icon={LayoutGrid}
        title={t('set.m.launcher')}
        what={t('set.m.launcherWhat')}
        status={
          available ? (
            <Switch
              testID="launcher-toggle"
              accessibilityLabel={t('set.m.launcher')}
              value={quick.launcher}
              onValueChange={(v) => {
                setLauncherEnabled(v);
                quick.setLauncher(isLauncherEnabled() || v);
              }}
              trackColor={{ false: th.borderStrong, true: th.brand }}
              thumbColor="#FFFFFF"
            />
          ) : (
            unavailable
          )
        }
        // "Shu yerda belgini yoqing" qadami olib tashlandi - switch yonida turibdi, takror edi.
        numbered={false}
        steps={[t('set.m.launcherStep2')]}
      />

      <MethodCard
        testID="quick-side"
        icon={Smartphone}
        title={t('set.m.side')}
        what={t('set.m.sideWhat')}
        status={
          !available ? (
            unavailable
          ) : quick.launcher ? (
            <StatusPill testID="side-status" label={t('set.m.sidePhone')} style={s.pill} />
          ) : (
            // Yon tugma "Yozish" belgisini ochadi - belgi o'chiq bo'lsa sozlab bo'lmaydi.
            <StatusPill testID="side-status" label={t('set.m.sideNeedsIcon')} tone="warn" style={s.pill} />
          )
        }
        // Samsung va Pixel - muqobil yo'llar, ketma-ket qadam emas: raqamsiz.
        numbered={false}
        steps={[t('set.m.sideSamsung'), t('set.m.sidePixel')]}
      />

      <MethodCard
        testID="quick-tile"
        icon={PanelTop}
        title={t('set.m.tile')}
        what={t('set.m.tileWhat')}
        status={
          !available ? (
            unavailable
          ) : tile ? (
            <StatusPill testID="tile-status" label={t(TILE_PILL[tile].key)} tone={TILE_PILL[tile].tone} style={s.pill} />
          ) : null
        }
        action={<CardButton testID="tile-add" icon={Plus} title={t('set.m.tileAdd')} disabled={!available} onPress={() => void addTile()} />}
        numbered={false}
        steps={[t('set.m.tileManual')]}
        open={tileHelp}
        onToggle={setTileHelp}
      />

      <MethodCard
        testID="quick-shortcut"
        icon={AppWindow}
        title={t('set.m.shortcut')}
        what={t('set.m.shortcutWhat')}
        // Yorliq JS'da o'rnatiladi (expo-quick-actions) - native modulsiz ham doim bor.
        status={<StatusPill label={t('set.always')} tone="good" style={s.pill} />}
        steps={[t('set.m.shortcutStep1'), t('set.m.shortcutStep2')]}
      />

      <View style={s.limits}>
        <Collapsible title={t('set.limits')} testID="quick-limits">
          <StepList numbered={false} items={[t('set.limitUnlock'), t('set.limitPower'), t('set.limitLock')]} />
        </Collapsible>
      </View>
    </ScrollView>
  );
}

/**
 * Bitta usul kartasi: sarlavha qatori (belgi + nom + holat), ostida maqsad, ixtiyoriy
 * bitta tugma va yopiq "Qanday sozlash".
 */
function MethodCard({
  testID,
  icon,
  title,
  what,
  status,
  action,
  note,
  steps,
  numbered = true,
  open,
  onToggle,
}: {
  testID: string;
  icon: LucideIcon;
  title: string;
  what: string;
  status: ReactNode;
  action?: ReactNode;
  /** Tugma ostida doim ko'rinadigan qisqa xira qatorlar (yopiq bo'lmasligi kerak bo'lgan gap). */
  note?: string[];
  steps: string[];
  numbered?: boolean;
  open?: boolean;
  onToggle?: (open: boolean) => void;
}) {
  const t = useT();
  const th = useTheme();
  return (
    <View testID={testID} style={[s.card, { backgroundColor: th.surfaceAlt }]}>
      <View style={s.head}>
        <MethodIcon icon={icon} />
        <Text numberOfLines={2} style={[s.title, { color: th.text }]}>
          {title}
        </Text>
        {status}
      </View>
      <View style={s.body}>
        <Text style={[typeScale.sub, { color: th.textMuted }]}>{what}</Text>
        {action ? <View style={s.action}>{action}</View> : null}
        {note?.map((line) => (
          <Text key={line} style={[typeScale.caption, { color: th.textMuted }]}>
            {line}
          </Text>
        ))}
        <Collapsible title={t('set.howTo')} testID={`${testID}-howto`} open={open} onToggle={onToggle}>
          <StepList numbered={numbered} items={steps} />
        </Collapsible>
      </View>
    </View>
  );
}

/**
 * Karta belgisi. NIMA UCHUN `IconTile` emas: uning `plain` foni `surfaceAlt` - karta
 * fonining o'zi, belgi "havoda" qolardi. Sahifa foni (`bg`) karta ustida aniq ko'rinadi.
 */
function MethodIcon({ icon: Icon }: { icon: LucideIcon }) {
  const th = useTheme();
  return (
    <View style={[s.tile, { backgroundColor: th.bg }]}>
      <Icon size={iconSize.md} color={th.textSoft} strokeWidth={stroke.regular} />
    </View>
  );
}

/** Karta ichidagi kichik tugma: `secondary` foni ham `surfaceAlt` - sahifa foni bilan ajralsin. */
function CardButton(p: { testID: string; icon: LucideIcon; title: string; disabled?: boolean; onPress: () => void }) {
  const th = useTheme();
  return (
    <Button
      small
      variant="secondary"
      testID={p.testID}
      icon={p.icon}
      title={p.title}
      disabled={p.disabled}
      onPress={p.onPress}
      style={[s.button, { backgroundColor: th.bg, borderColor: th.borderStrong }]}
    />
  );
}

const s = StyleSheet.create({
  intro: { paddingHorizontal: 4, marginBottom: 16 },
  card: { borderRadius: radius.lg, padding: 16, gap: 8, marginBottom: 12 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  tile: { width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  title: { flex: 1, minWidth: 0, fontSize: 16, lineHeight: 21, fontWeight: '600' },
  // Uzun holat matni (ru) sarlavhani butunlay siqib qo'ymasin.
  pill: { maxWidth: '50%', flexShrink: 1 },
  // Matn sarlavha bilan bir chiziqda boshlanadi (belgi 40 + oraliq 12).
  body: { paddingLeft: 52, gap: 4 },
  action: { paddingTop: 4, alignItems: 'flex-start' },
  button: { borderWidth: StyleSheet.hairlineWidth, paddingHorizontal: 12 },
  limits: { paddingHorizontal: 4, marginTop: 4 },
});
