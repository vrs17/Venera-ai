/**
 * `waitForForeground` / `yieldToUi` (src/lib/appState.ts): fonda JS taymerlari
 * to'xtaydi - shuning uchun kutish devor soati bilan ham tekshiriladi va
 * fonda hech qachon taymer kutilmaydi.
 */
import { AppState } from 'react-native';

import { waitForForeground, yieldToUi } from '@/lib/appState';

type Listener = (s: string) => void;
let listeners: Listener[] = [];
const appState = AppState as unknown as { currentState: string; addEventListener: jest.Mock };

beforeEach(() => {
  listeners = [];
  appState.addEventListener.mockImplementation((_type: string, fn: Listener) => {
    listeners.push(fn);
    return { remove: () => (listeners = listeners.filter((l) => l !== fn)) };
  });
});

afterEach(() => {
  jest.useRealTimers();
});

describe('waitForForeground', () => {
  it('resolves at once when the app is on screen', async () => {
    appState.currentState = 'active';
    await expect(waitForForeground(5000)).resolves.toBe(true);
    expect(listeners).toHaveLength(0);
  });

  it('waits for the permission dialog to close (background -> active)', async () => {
    appState.currentState = 'background';
    const p = waitForForeground(5000);
    appState.currentState = 'active';
    listeners.forEach((l) => l('active'));
    await expect(p).resolves.toBe(true);
    expect(listeners).toHaveLength(0);
  });

  it('gives up after the timeout', async () => {
    jest.useFakeTimers();
    appState.currentState = 'background';
    const p = waitForForeground(5000);
    jest.advanceTimersByTime(5000);
    await expect(p).resolves.toBe(false);
  });

  it('a late return (timer was frozen in the background) does not start a surprise recording', async () => {
    appState.currentState = 'background';
    let t = 0;
    const p = waitForForeground(5000, () => t);
    t = 60_000; // foydalanuvchi 1 daqiqadan keyin qaytdi
    listeners.forEach((l) => l('active'));
    await expect(p).resolves.toBe(false);
  });
});

describe('yieldToUi', () => {
  it('returns immediately in the background (never waits on a frozen timer)', async () => {
    appState.currentState = 'background';
    await expect(yieldToUi()).resolves.toBeUndefined();
    expect(listeners).toHaveLength(0);
  });

  it('yields one macrotask in the foreground and also ends if the app leaves the screen', async () => {
    jest.useFakeTimers();
    appState.currentState = 'active';
    const p1 = yieldToUi();
    jest.advanceTimersByTime(0);
    await expect(p1).resolves.toBeUndefined();
    const p2 = yieldToUi();
    listeners.forEach((l) => l('background'));
    await expect(p2).resolves.toBeUndefined();
  });
});
