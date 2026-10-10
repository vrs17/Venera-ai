import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

import { DICTS, interpolate, translate, UI_LANGS } from '@/i18n';
import { uz } from '@/i18n/uz';

describe('i18n', () => {
  it('every language has exactly the uz keys, all non-empty', () => {
    const keys = Object.keys(uz).sort();
    for (const lang of UI_LANGS) {
      expect(Object.keys(DICTS[lang]).sort()).toEqual(keys);
      for (const k of keys) expect(DICTS[lang][k as keyof typeof uz].trim()).not.toBe('');
    }
  });

  it('placeholders match across languages', () => {
    const ph = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(',');
    for (const k of Object.keys(uz) as (keyof typeof uz)[]) {
      expect([k, ph(DICTS.ru[k])]).toEqual([k, ph(uz[k])]);
      expect([k, ph(DICTS.en[k])]).toEqual([k, ph(uz[k])]);
    }
  });

  it('Uzbek Latin is the default and interpolates', () => {
    expect(translate('uz', 'list.openItems', { n: 3 })).toBe('3 ta ochiq vazifa');
    expect(translate('ru', 'status.ready')).toBe('Готово');
    expect(interpolate('{a} {b}', { a: 1 })).toBe('1 {b}');
    // Lotin yozuvi: kirill harflari yo'q.
    for (const v of Object.values(uz)) expect(v).not.toMatch(/[Ѐ-ӿ]/);
  });

  it('the product is "Barno AI": no user-visible string says Venera (any language, any case)', () => {
    for (const lang of UI_LANGS) {
      for (const [k, v] of Object.entries(DICTS[lang])) expect([lang, k, v]).toEqual([lang, k, expect.not.stringMatching(/venera|венера/i)]);
    }
    expect(translate('uz', 'app.name')).toBe('Barno AI');
    expect(translate('ru', 'login.title')).toBe('Barno AI');
    expect(translate('uz', 'shell.offlineBody')).toMatch(/^Barnoga ulanib/);
    expect(translate('ru', 'shell.errorTitle')).toBe('Не удалось открыть Barno AI');
  });

  it('native labels (tile, launcher, shortcut) and the launcher name follow the rename', () => {
    const res = join(__dirname, '../modules/venera-entry/android/src/main/res');
    for (const dir of readdirSync(res).filter((d) => d.startsWith('values'))) {
      for (const f of readdirSync(join(res, dir)).filter((x) => x.endsWith('.xml'))) {
        const texts = [...readFileSync(join(res, dir, f), 'utf8').matchAll(/<string [^>]*>([^<]*)<\/string>/g)].map((m) => m[1]);
        for (const text of texts) expect([dir, f, text]).toEqual([dir, f, expect.not.stringMatching(/venera/i)]);
      }
    }
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const make = require('../app.config').default as (ctx: { config: object }) => Record<string, any>;
    const c = make({ config: {} });
    expect(c.name).toBe('Barno AI');
    const audio = c.plugins.find((p: unknown) => Array.isArray(p) && p[0] === 'expo-audio');
    expect(audio[1].microphonePermission).toMatch(/^Barno AI /);
    // Texnik nomlar o'zgarmaydi: o'rnatilgan ilova ustidan yangilanadi, havolalar ishlaydi.
    expect(c.scheme).toBe('venera-rec');
    expect(c.android.package).toBe('uz.brbtech.venera.meetings');
  });
});
