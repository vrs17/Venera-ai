/**
 * Ildiz `_layout` ning `unstable_settings.anchor`: yon tugma / plitka deep link'i
 * (`venera-rec://record`) ilovani SOVUQ ishga tushirsa ham stek ostida asosiy ekran
 * (chat) bo'lsin - "Orqaga" ilovadan chiqarmasin, yozuvdan keyingi batafsil
 * ekrandan ham chatga qaytilsin.
 */
import { router, Stack } from 'expo-router';
import { act, renderRouter, screen } from 'expo-router/testing-library';
import { Text } from 'react-native';

import { unstable_settings } from '@/app/_layout';

const routes = {
  _layout: { default: () => <Stack />, unstable_settings },
  index: () => <Text>chat-screen</Text>,
  record: () => <Text>record-screen</Text>,
  'meeting/[id]': () => <Text>meeting-screen</Text>,
};

describe('root anchor (deep link cold start)', () => {
  it('anchors the stack on the chat', () => {
    expect(unstable_settings).toEqual({ anchor: 'index' });
  });

  it('cold start on /record: the chat is underneath; after stop the detail screen still goes back to it', async () => {
    await renderRouter(routes, { initialUrl: '/record?src=sidekey' });
    expect(screen.getByText('record-screen')).toBeTruthy();
    expect(router.canGoBack()).toBe(true);
    await act(async () => {
      router.replace('/meeting/abc?local=1');
    });
    expect(screen.getByText('meeting-screen')).toBeTruthy();
    expect(router.canGoBack()).toBe(true);
    await act(async () => {
      router.back();
    });
    expect(screen.getByText('chat-screen')).toBeTruthy();
  });
});
