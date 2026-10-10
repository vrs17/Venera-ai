/**
 * Profil: kim kirgan (HRM'dan kelgan ism, email, lavozim, bo'lim). Faqat o'qish -
 * ma'lumot HRM'da o'zgartiriladi, ilovada tahrir yo'q.
 *
 * Qiymatlar `selectable`: emailni bosib turib nusxalash mumkin (masalan, IT'ga yozish uchun).
 * Bo'sh maydon "Ko'rsatilmagan" deb aytiladi - qator jim yo'qolmasin, nima yetishmasligi ko'rinsin.
 */
import { Briefcase, Building, Mail } from 'lucide-react-native';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '@/features/auth/authStore';
import { useT } from '@/features/settings/settingsStore';
import { Avatar } from '@/ui/Avatar';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';
import { type as typeScale } from '@/ui/tokens';

export default function AccountScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const user = useAuth((s) => s.user);
  const name = user?.fullName || user?.email || '-';

  const field = (value: string | null | undefined) => ({
    subtitle: value || t('set.notSet'),
    selectableSubtitle: !!value,
  });

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}>
      <View style={s.hero} testID="account-hero">
        <Avatar name={user?.fullName || user?.email} size={72} />
        <Text selectable style={[typeScale.title, s.center, { color: th.text, marginTop: 12 }]}>
          {name}
        </Text>
        {user?.position ? <Text style={[typeScale.sub, s.center, { color: th.textMuted, marginTop: 2 }]}>{user.position}</Text> : null}
      </View>

      <ListGroup>
        <ListRow testID="account-email" icon={Mail} title={t('set.email')} {...field(user?.email)} />
        <ListRow testID="account-position" icon={Briefcase} title={t('set.position')} {...field(user?.position)} />
        <ListRow testID="account-department" icon={Building} title={t('set.department')} {...field(user?.department)} />
      </ListGroup>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  hero: { alignItems: 'center', paddingTop: 8, paddingBottom: 24 },
  center: { textAlign: 'center' },
});
