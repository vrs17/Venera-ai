/**
 * Kirish ekranidagi «Maxfiylik siyosati» havolasi (Google Play: siyosat ilova ichida ham,
 * kirishdan OLDIN ham ochilishi kerak). SSO sozlamasi yuklanmasa ham havola ko'rinadi.
 */
import { fireEvent, render, screen } from '@testing-library/react-native';
import { Linking } from 'react-native';

import LoginScreen from '@/app/login';
import type { Services } from '@/services';

import { fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => ({ router: { push: jest.fn(), replace: jest.fn() } }));

function servicesWithoutSso(): Services {
  const base = fakeServices();
  // SSO sozlamasi olinmadi (tarmoq yo'q) - ekran zahira shaklni ko'rsatadi.
  const auth = { ssoConfig: jest.fn(async () => Promise.reject(new Error('offline'))) };
  return { ...base, auth: auth as unknown as Services['auth'] };
}

describe('Login screen privacy link', () => {
  it('opens the fixed public privacy page', async () => {
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
    try {
      await render(
        <Providers services={servicesWithoutSso()}>
          <LoginScreen />
        </Providers>,
      );
      const link = await screen.findByTestId('login-privacy');
      expect(screen.getByText('Maxfiylik siyosati')).toBeTruthy();
      await fireEvent.press(link);
      expect(open).toHaveBeenCalledWith('https://llm.brb-tech.uz/privacy');
    } finally {
      open.mockRestore();
    }
  });
});
