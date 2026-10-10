/**
 * Ovozli suhbat sozlamalari (`/settings/voice`): ovoz va tezlik radio ro'yxati, matnni
 * ko'rsatish kaliti, "Ovozni sinash" (yuklanish/o'qilish belgisi, chiqishda to'xtaydi),
 * o'zbekchadan boshqa tilda izoh.
 */
import { act, fireEvent, render, screen } from '@testing-library/react-native';

import VoiceSettingsScreen from '@/app/settings/voice';
import { useSettings } from '@/features/settings/settingsStore';
import * as readAloud from '@/features/voice/readAloud';
import { useVoiceSettings } from '@/features/voice/voiceSettings';

import { fakeServices, Providers } from './fixtures/fakeServices';

const controls = { toggle: jest.fn(), pause: jest.fn(), resume: jest.fn(), stop: jest.fn(), preview: jest.fn() };

beforeEach(() => {
  jest.spyOn(readAloud, 'useReadAloudControls').mockReturnValue(controls);
  readAloud.useReadAloud.setState({ key: null, phase: 'idle', index: 0, total: null });
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
  useVoiceSettings.setState({ voice: 'uz_female_calm', speed: 'normal', showText: true, earpiece: false });
});

afterEach(() => {
  jest.restoreAllMocks();
});

async function renderSettings() {
  await render(
    <Providers services={fakeServices()}>
      <VoiceSettingsScreen />
    </Providers>,
  );
}

describe('Voice settings screen', () => {
  it('voice and speed are radio lists; the choice persists in the voice store', async () => {
    await renderSettings();
    expect(screen.getByText('Ovoz')).toBeTruthy();
    expect(screen.getByTestId('voice-female').props.accessibilityState).toMatchObject({ checked: true });
    expect(screen.getByTestId('voice-male').props.accessibilityState).toMatchObject({ checked: false });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-male'));
    });
    expect(useVoiceSettings.getState().voice).toBe('uz_male_news');
    expect(screen.getByTestId('voice-male').props.accessibilityState).toMatchObject({ checked: true });

    expect(screen.getByTestId('speed-normal').props.accessibilityState).toMatchObject({ checked: true });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('speed-fast'));
    });
    expect(useVoiceSettings.getState().speed).toBe('fast');
    expect(screen.getByText('Tez')).toBeTruthy();
  });

  it('show text is a switch (the whole row toggles)', async () => {
    await renderSettings();
    expect(screen.getByTestId('voice-show-text').props.accessibilityState).toMatchObject({ checked: true });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-show-text'));
    });
    expect(useVoiceSettings.getState().showText).toBe(false);
  });

  it('preview: plays the sample, shows loading / playing, stops when leaving', async () => {
    const stop = jest.spyOn(readAloud, 'stopReadAloud');
    await renderSettings();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-preview'));
    });
    expect(controls.preview).toHaveBeenCalledTimes(1);
    await act(async () => {
      readAloud.useReadAloud.setState({ key: readAloud.PREVIEW_KEY, phase: 'loading', index: 0, total: null });
    });
    expect(screen.getByTestId('voice-preview-loading')).toBeTruthy();
    await act(async () => {
      readAloud.useReadAloud.setState({ phase: 'playing', index: 1 });
    });
    expect(screen.getByTestId('icon-Square')).toBeTruthy();
    expect(screen.getByTestId('voice-preview').props.accessibilityLabel).toBe("Ovozni sinash, To'xtatish");
    await screen.unmount();
    expect(stop).toHaveBeenCalled();
  });

  it('leaving does not stop an answer being read in chat', async () => {
    const stop = jest.spyOn(readAloud, 'stopReadAloud');
    await renderSettings();
    await act(async () => {
      readAloud.useReadAloud.setState({ key: 'ex-1', phase: 'playing', index: 1 });
    });
    await screen.unmount();
    expect(stop).not.toHaveBeenCalled();
  });

  it('Uzbek-only footer for other languages', async () => {
    await renderSettings();
    expect(screen.queryByText("Ovoz hozircha faqat o'zbek tilida")).toBeNull();
    await act(async () => {
      useSettings.getState().set({ uiLang: 'ru' });
    });
    expect(screen.getByText('Голос пока доступен только на узбекском')).toBeTruthy();
    expect(screen.getByText('Мужской - диктор')).toBeTruthy();
    // Bu tilda ovoz yo'q - javob baribir matn: "matnni ko'rsatish" kaliti o'chiq, sababi yozilgan.
    expect(screen.getByText('На этом языке ответ всегда показывается текстом')).toBeTruthy();
    expect(screen.getByTestId('voice-show-text').props.accessibilityState).toMatchObject({ checked: true, disabled: true });
  });
});
