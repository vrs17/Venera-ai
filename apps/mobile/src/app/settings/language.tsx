/**
 * Interfeys tili. Har til O'Z yozuvida ("Русский"), ostida joriy tildagi nomi
 * ("Ruscha") - interfeys tushunilmasa ham odam o'z tilini topsin.
 * Bosilganda til darhol almashadi va sahifada qolamiz (sarlavha ham shu zahoti yangilanadi).
 */
import { ScrollView } from 'react-native';

import { LANG_ENDONYM } from '@/features/settings/langNames';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { UI_LANGS } from '@/i18n';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';

export default function LanguageScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const uiLang = useSettings((s) => s.uiLang);
  const set = useSettings((s) => s.set);

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}>
      <ListGroup>
        {UI_LANGS.map((l) => {
          const local = t(`lang.${l}`);
          return (
            <ListRow
              key={l}
              testID={`uilang-${l}`}
              title={LANG_ENDONYM[l]}
              subtitle={local !== LANG_ENDONYM[l] ? local : null}
              right={{ kind: 'check', checked: uiLang === l }}
              onPress={() => set({ uiLang: l })}
            />
          );
        })}
      </ListGroup>
    </ScrollView>
  );
}
