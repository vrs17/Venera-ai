/**
 * Yopishqoq pleer (spec 7.4, 3.2 #28). Audio `GET /meetings/{id}/audio`
 * dan `{uri, headers: {Authorization}}` bilan olinadi (m4a, Range -
 * istalgan joyga o'tish mumkin).
 *
 * `seek` prop: xulosa/transkriptdagi dalil bosilganda shu soniyaga o'tib
 * ijro etadi.
 */
import { useAudioPlayer, useAudioPlayerStatus, type AudioSource } from 'expo-audio';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Muted } from '@/ui/components';
import { useTheme } from '@/ui/theme';

import { formatClock } from './formatDate';

export interface SeekRequest {
  t: number;
  n: number;
}

export function PlayerBar({ meetingId, available, seek }: { meetingId: string; available: boolean; seek: SeekRequest | null }) {
  const t = useT();
  const { session, meetings } = useServices();
  const [source, setSource] = useState<AudioSource>(null);

  useEffect(() => {
    if (!available) return;
    let alive = true;
    session
      .getToken()
      .then((token) => {
        if (alive) setSource({ uri: meetings.audioUrl(meetingId), headers: { Authorization: `Bearer ${token}`, 'X-Venera-Client': 'mobile' } });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [available, meetingId, meetings, session]);

  if (!available) return <Muted>{t('player.unavailable')}</Muted>;
  if (!source) return null;
  return <Player source={source} seek={seek} />;
}

function Player({ source, seek }: { source: AudioSource; seek: SeekRequest | null }) {
  const th = useTheme();
  const t = useT();
  const player = useAudioPlayer(source, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);
  const [width, setWidth] = useState(1);

  useEffect(() => {
    if (!seek) return;
    void player.seekTo(seek.t).then(() => player.play()).catch(() => {});
  }, [seek, player]);

  const duration = status.duration || 0;
  const pos = Math.min(status.currentTime || 0, duration || Infinity);
  const ratio = duration > 0 ? pos / duration : 0;

  return (
    <View style={[s.bar, { backgroundColor: th.surface, borderColor: th.border }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={status.playing ? t('player.pause') : t('player.play')}
        onPress={() => (status.playing ? player.pause() : player.play())}
        style={[s.play, { backgroundColor: th.primary }]}>
        <Text style={{ color: th.primaryText, fontSize: 16 }}>{status.playing ? '❚❚' : '▶'}</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('player.back10')}
        onPress={() => void player.seekTo(Math.max(0, pos - 10))}
        style={s.skip}>
        <Text style={{ color: th.text }}>-10</Text>
      </Pressable>
      <View style={{ flex: 1 }}>
        <Pressable
          // TalkBack: sozlanadigan element - yuqoriga/pastga surish 10 s siljitadi.
          accessibilityRole="adjustable"
          accessibilityLabel={t('player.position')}
          accessibilityValue={{ min: 0, max: Math.round(duration), now: Math.round(pos), text: `${formatClock(pos)} / ${formatClock(duration)}` }}
          accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
          onAccessibilityAction={(e) => {
            if (e.nativeEvent.actionName === 'increment') void player.seekTo(Math.min(duration, pos + 10));
            if (e.nativeEvent.actionName === 'decrement') void player.seekTo(Math.max(0, pos - 10));
          }}
          onLayout={(e: LayoutChangeEvent) => setWidth(Math.max(1, e.nativeEvent.layout.width))}
          onPress={(e) => duration > 0 && void player.seekTo((e.nativeEvent.locationX / width) * duration)}
          style={[s.track, { backgroundColor: th.surfaceAlt }]}>
          <View style={[s.fill, { width: `${Math.round(ratio * 100)}%`, backgroundColor: th.primary }]} />
        </Pressable>
        <Text style={[s.time, { color: th.textMuted }]}>
          {formatClock(pos)} / {formatClock(duration)}
        </Text>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('player.fwd10')}
        onPress={() => void player.seekTo(Math.min(duration, pos + 10))}
        style={s.skip}>
        <Text style={{ color: th.text }}>+10</Text>
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  bar: { flexDirection: 'row', alignItems: 'center', padding: 8, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, marginBottom: 10 },
  play: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  skip: { paddingHorizontal: 8, paddingVertical: 6 },
  track: { height: 8, borderRadius: 4, overflow: 'hidden', marginTop: 6 },
  fill: { height: 8 },
  time: { fontSize: 11, marginTop: 4 },
});
