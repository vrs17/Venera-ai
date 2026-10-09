/**
 * Jest uchun native modul mocklari. jest-expo ko'p expo-* modullarini o'zi
 * mock qiladi; expo-audio (yozuvchi/pleer) va clipboard bu yerda - testlar
 * hech qachon haqiqiy mikrofon yoki tarmoqqa tegmaydi.
 */
/* eslint-disable no-undef */
jest.mock('expo-audio', () => {
  const recorder = {
    uri: 'file:///doc/rec-1.aac',
    isRecording: false,
    prepareToRecordAsync: jest.fn(async () => {}),
    record: jest.fn(),
    pause: jest.fn(),
    stop: jest.fn(async () => {}),
    getStatus: jest.fn(() => ({ canRecord: true, isRecording: false, durationMillis: 0, mediaServicesDidReset: false, metering: -30, url: null })),
  };
  const player = {
    play: jest.fn(),
    pause: jest.fn(),
    seekTo: jest.fn(async () => {}),
    remove: jest.fn(),
  };
  return {
    __recorder: recorder,
    __player: player,
    AudioQuality: { MIN: 0, LOW: 32, MEDIUM: 64, HIGH: 96, MAX: 127 },
    IOSOutputFormat: { MPEG4AAC: 'aac ' },
    useAudioRecorder: jest.fn(() => recorder),
    useAudioRecorderState: jest.fn(() => ({ canRecord: true, isRecording: false, durationMillis: 0, mediaServicesDidReset: false, url: null })),
    useAudioPlayer: jest.fn(() => player),
    useAudioPlayerStatus: jest.fn(() => ({ currentTime: 0, duration: 120, playing: false, isLoaded: true })),
    setAudioModeAsync: jest.fn(async () => {}),
    requestRecordingPermissionsAsync: jest.fn(async () => ({ granted: true, status: 'granted' })),
    requestNotificationPermissionsAsync: jest.fn(async () => ({ granted: true, status: 'granted' })),
    getRecordingPermissionsAsync: jest.fn(async () => ({ granted: true, status: 'granted' })),
  };
});

jest.mock('expo-clipboard', () => ({
  setStringAsync: jest.fn(async () => true),
  getStringAsync: jest.fn(async () => ''),
}));

jest.mock('expo-intent-launcher', () => ({
  ActivityAction: {
    IGNORE_BATTERY_OPTIMIZATION_SETTINGS: 'android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS',
    APPLICATION_DETAILS_SETTINGS: 'android.settings.APPLICATION_DETAILS_SETTINGS',
  },
  startActivityAsync: jest.fn(async () => ({ resultCode: 0 })),
}));

// lucide-react-native: SVG belgilar Jest'da kerak emas - nomli bo'sh ko'rinish (testID
// orqali qaysi belgi chizilganini tekshirish mumkin).
jest.mock('lucide-react-native', () => {
  const React = require('react');
  const { View } = require('react-native');
  return new Proxy(
    {},
    {
      get: (_t, name) => {
        if (name === '__esModule') return true;
        return function Icon() {
          return React.createElement(View, { testID: `icon-${String(name)}` });
        };
      },
    },
  );
});
