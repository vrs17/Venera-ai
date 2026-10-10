/**
 * Mavzu: tizimga ergashish, yorug' yoki qorong'i. Tanlov darhol qo'llanadi -
 * sahifaning o'zi ham shu zahoti yangi ranglarda chiziladi (natija ko'rinib turadi).
 */
import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react-native';
import { ScrollView } from 'react-native';

import { useSettings, useT, type ThemePref } from '@/features/settings/settingsStore';
import type { TKey } from '@/i18n';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';

const OPTIONS: { value: ThemePref; icon: LucideIcon; title: TKey; hint?: TKey }[] = [
  { value: 'system', icon: Monitor, title: 'settings.themeSystem', hint: 'set.themeSystemHint' },
  { value: 'light', icon: Sun, title: 'settings.themeLight' },
  { value: 'dark', icon: Moon, title: 'settings.themeDark' },
];

export default function ThemeScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const themePref = useSettings((s) => s.themePref);
  const set = useSettings((s) => s.set);

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}>
      <ListGroup>
        {OPTIONS.map((o) => (
          <ListRow
            key={o.value}
            testID={`theme-${o.value}`}
            icon={o.icon}
            title={t(o.title)}
            subtitle={o.hint ? t(o.hint) : null}
            right={{ kind: 'check', checked: themePref === o.value }}
            onPress={() => set({ themePref: o.value })}
          />
        ))}
      </ListGroup>
    </ScrollView>
  );
}
