/**
 * Ilova haqida: versiya va server manzili - xato haqida xabar berilganda IT so'raydigan
 * ikki narsa. Server manzilini bosib turib nusxalash mumkin.
 */
import { Globe, Info } from 'lucide-react-native';
import { ScrollView } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';

export default function AboutScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const services = useServices();

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}>
      <ListGroup>
        <ListRow testID="about-version" icon={Info} title={t('set.versionLabel')} right={{ kind: 'value', text: services.appVersion }} />
        <ListRow testID="about-server" icon={Globe} title={t('set.serverLabel')} subtitle={services.apiBaseUrl} selectableSubtitle />
      </ListGroup>
    </ScrollView>
  );
}
