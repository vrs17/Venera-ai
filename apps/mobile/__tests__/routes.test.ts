/**
 * Ildiz stekida ro'yxatdan o'tgan har bir ekran nomi haqiqiy marshrut fayliga mos
 * (xato nomni expo-router faqat ogohlantirish bilan o'tkazib yuboradi - sarlavha jim
 * yo'qoladi) va Sozlamalar sahifalari faqat kirgandan keyin ochiladi.
 */
import { existsSync, readFileSync } from 'fs';
import { join } from 'path';

const APP = join(__dirname, '../src/app');
const layout = readFileSync(join(APP, '_layout.tsx'), 'utf8');

function protectedBlock(guard: string): string {
  const start = layout.indexOf(`<Stack.Protected guard={${guard}}>`);
  expect(start).toBeGreaterThan(-1);
  return layout.slice(start, layout.indexOf('</Stack.Protected>', start));
}

describe('root stack routes', () => {
  it('every Stack.Screen name has a route file', () => {
    const names = [...layout.matchAll(/<Stack\.Screen name="([^"]+)"/g)].map((m) => m[1]);
    expect(names.length).toBeGreaterThan(5);
    for (const name of names) expect([name, existsSync(join(APP, `${name}.tsx`))]).toEqual([name, true]);
  });

  it('settings hub and sub-screens are registered inside the signed-in guard', () => {
    const signedIn = protectedBlock('signedIn');
    for (const name of [
      'meetings',
      'meeting/[id]',
      'action-items',
      'settings/index',
      'settings/account',
      'settings/connections',
      'settings/quick',
      'settings/recording',
      'settings/language',
      'settings/theme',
      'settings/about',
      'settings/voice',
      'settings/calls',
      'import',
      'voice',
    ]) {
      expect([name, signedIn.includes(`<Stack.Screen name="${name}"`)]).toEqual([name, true]);
    }
    // Eski yassi `settings.tsx` qolmasin - `/settings` ikki faylga bo'linib ketmasin.
    expect(existsSync(join(APP, 'settings.tsx'))).toBe(false);
    // Yozish hech qachon login kutmaydi (spec 7.5): `record` himoyadan tashqarida.
    expect(signedIn.includes('name="record"')).toBe(false);
    expect(layout.includes('<Stack.Screen name="record"')).toBe(true);
  });
});
