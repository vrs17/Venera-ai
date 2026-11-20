import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

import { DICTS, interpolate, translate, UI_LANGS } from '@/i18n';
import { callsPart } from '@/i18n/parts/calls';
import { meetingChatPart } from '@/i18n/parts/meetingChat';
import { minutesPart } from '@/i18n/parts/minutes';
import { nav } from '@/i18n/parts/nav';
import { recordingsPart } from '@/i18n/parts/recordings';
import { settingsPart } from '@/i18n/parts/settings';
import { sharePart } from '@/i18n/parts/share';
import { uz } from '@/i18n/uz';

/** Bo'lim fayllari (parallel quruvchilar): nomi, lug'ati, kalit prefiksi. */
const PARTS = [
  ['nav', nav, 'nav.'],
  ['settings', settingsPart, 'set.'],
  ['recordings', recordingsPart, 'recs.'],
  ['share', sharePart, 'share.'],
  ['calls', callsPart, 'calls.'],
  ['minutes', minutesPart, 'minutes.'],
  ['meetingChat', meetingChatPart, 'mchat.'],
] as const;

describe('i18n', () => {
  it('every language has exactly the uz keys, all non-empty', () => {
    const keys = Object.keys(uz).sort();
    for (const lang of UI_LANGS) {
      expect(Object.keys(DICTS[lang]).sort()).toEqual(keys);
      for (const k of keys) expect(DICTS[lang][k as keyof typeof uz].trim()).not.toBe('');
    }
  });

  it('parts: uz/ru/en have the same keys, own prefix only, no overlap, all merged into the dictionaries', () => {
    const seen = new Set<string>();
    for (const [name, part, prefix] of PARTS) {
      const keys = Object.keys(part.uz).sort();
      expect([name, keys.length > 0]).toEqual([name, true]);
      for (const lang of UI_LANGS) {
        const dict = part[lang] as Record<string, string>;
        expect([name, lang, Object.keys(dict).sort()]).toEqual([name, lang, keys]);
        // Yoyilgan va boshqa kalit ustidan yozilmagan: asosiy lug'atda aynan shu qiymat.
        for (const k of keys) expect([lang, k, (DICTS[lang] as Record<string, string>)[k]]).toEqual([lang, k, dict[k]]);
      }
      for (const k of keys) {
        expect([name, k.startsWith(prefix)]).toEqual([name, true]);
        expect([k, seen.has(k)]).toEqual([k, false]);
        seen.add(k);
      }
    }
    // Prefikslar faqat bo'lim fayllariga tegishli: asosiy uz.ts ichida qo'lda yozilgan
    // `nav.`/`set.`/`recs.`/`share.`/`calls.`/`minutes.`/`mchat.` kaliti bo'lmasin (bo'lim fayli uni jim ustidan yozib yuborardi).
    for (const k of Object.keys(uz)) if (/^(nav|set|recs|share|calls|minutes|mchat)\./.test(k)) expect([k, seen.has(k)]).toEqual([k, true]);
    for (const lang of UI_LANGS) {
      const src = readFileSync(join(__dirname, `../src/i18n/${lang}.ts`), 'utf8');
      expect([lang, src.match(/^\s*['"](nav|set|recs|share|calls|minutes|mchat)\./m)]).toEqual([lang, null]);
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

  it('the meetings section is called "Plaud" (as «🎙 Plaud» in Slack/Telegram); recordings as things stay "yozuv"', () => {
    for (const lang of UI_LANGS) {
      for (const k of ['nav.recordings', 'shell.meetings', 'settings.meetings', 'list.title'] as const) {
        expect([lang, k, translate(lang, k)]).toEqual([lang, k, 'Plaud']);
      }
      // Bo'limga ishora qiluvchi matnlar ("holati Plaud'da", "Plaud'ga o'tish", "Plaud bo'limi yoqilmagan").
      for (const k of ['calls.queued', 'calls.import.toRecordings', 'recs.up.disabledBody'] as const) {
        expect([lang, k, translate(lang, k)]).toEqual([lang, k, expect.stringContaining('Plaud')]);
      }
    }
    expect(translate('uz', 'calls.queued')).toBe("Yuborilmoqda - holati Plaud'da");
    expect(translate('uz', 'calls.import.toRecordings')).toBe("Plaud'ga o'tish");
    expect(translate('ru', 'calls.import.toRecordings')).toBe('Открыть Plaud');
    // Yozuvlar NARSA sifatida - o'zgarmaydi ("Yozuvlar | Qo'ng'iroqlar" tabi 2026-11-12 da olib tashlangan).
    expect(translate('uz', 'list.sessionExpired')).toMatch(/Yozuvlar telefonda saqlanib turibdi/);
    expect(translate('uz', 'recs.listFailed')).toBe("Yozuvlarni yuklab bo'lmadi");
    expect(translate('uz', 'recs.emptyTitle')).toBe("Hali yozuv yo'q");
    // Eski bo'lim nomi hech bir uz matnida qolmadi.
    for (const v of Object.values(uz)) expect(v).not.toMatch(/Yozuvlar(da|ga)\b|Yig'ilish yozuvlari/);
  });

  it('the product is "Barno": no user-visible string says Venera (any language, any case)', () => {
    for (const lang of UI_LANGS) {
      for (const [k, v] of Object.entries(DICTS[lang])) expect([lang, k, v]).toEqual([lang, k, expect.not.stringMatching(/venera|венера/i)]);
    }
    expect(translate('uz', 'app.name')).toBe('Barno');
    expect(translate('ru', 'login.title')).toBe('Barno');
    expect(translate('uz', 'shell.offlineBody')).toMatch(/^Barnoga ulanib/);
    expect(translate('ru', 'shell.errorTitle')).toBe('Не удалось открыть Barno');
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
    expect(c.name).toBe('Barno');
    const audio = c.plugins.find((p: unknown) => Array.isArray(p) && p[0] === 'expo-audio');
    expect(audio[1].microphonePermission).toMatch(/^Barno /);
    // Texnik nomlar o'zgarmaydi: o'rnatilgan ilova ustidan yangilanadi, havolalar ishlaydi.
    expect(c.scheme).toBe('venera-rec');
    expect(c.android.package).toBe('uz.brbtech.venera.meetings');
  });
});
