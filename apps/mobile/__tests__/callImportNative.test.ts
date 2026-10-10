/**
 * Qo'ng'iroq importining native qismi (Kotlin kompilyatsiya qilinmaydi - statik tekshiruv):
 * sof yordamchilar (importNames), native'siz no-op'lar, soxta modul bilan xato kodlari,
 * manifest (ImportActivity + ruxsatlar) va CallImport.kt dagi xavfsizlik qoidalari.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

const MOD = join(__dirname, '..', 'modules', 'venera-entry');
const read = (p: string) => readFileSync(join(MOD, p), 'utf8');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const names = require('../modules/venera-entry/importNames') as typeof import('../modules/venera-entry/importNames');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const entry = require('../modules/venera-entry') as typeof import('../modules/venera-entry');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const ne = require('../src/features/entry/nativeEntry') as Record<string, unknown>;

describe('importNames', () => {
  it('maps extension first, then MIME', () => {
    expect(names.contentTypeFor('Call recording Alisher_241010_143012.m4a')).toBe('audio/mp4');
    expect(names.contentTypeFor('x.MP4')).toBe('audio/mp4');
    expect(names.contentTypeFor('x.aac')).toBe('audio/aac');
    expect(names.contentTypeFor('x.mp3', 'audio/mp4')).toBeNull();
    expect(names.contentTypeFor('x.ogg')).toBeNull();
    expect(names.contentTypeFor('123', 'audio/x-m4a')).toBe('audio/mp4');
    expect(names.contentTypeFor('123', 'audio/aac; codecs=x')).toBe('audio/aac');
    expect(names.contentTypeFor('Mr. Smith', 'audio/mpeg')).toBeNull();
    expect(names.contentTypeFor(null, null)).toBeNull();
    expect(names.contentTypeFor('a.', 'audio/mp4')).toBe('audio/mp4');
  });

  it('validates import file names', () => {
    expect(names.isImportFileName('share_1728550000000_0_Call_recording_241010.m4a')).toBe(true);
    expect(names.isImportFileName('../x.m4a')).toBe(false);
    expect(names.isImportFileName('.x.m4a')).toBe(false);
    expect(names.isImportFileName('a..b.m4a')).toBe(false);
    expect(names.isImportFileName('a.m4a.json')).toBe(false);
    expect(names.isImportFileName('a.m4a.part')).toBe(false);
    expect(names.isImportFileName('Алишер.m4a')).toBe(false);
    expect(names.isImportFileName('a b.m4a')).toBe(false);
    expect(names.isImportFileName(`${'a'.repeat(117)}.m4a`)).toBe(false);
    expect(names.isImportFileName(`${'a'.repeat(116)}.m4a`)).toBe(true);
  });

  it('parses the files= list', () => {
    expect(names.parseImportFiles('a.m4a,b.aac,a.m4a,../c.m4a,,d.mp3')).toEqual(['a.m4a', 'b.aac']);
    expect(names.parseImportFiles(['a.m4a', 'b.m4a'])).toEqual(['a.m4a', 'b.m4a']);
    expect(names.parseImportFiles(null)).toEqual([]);
    const many = Array.from({ length: 30 }, (_, i) => `f${i}.m4a`).join(',');
    expect(names.parseImportFiles(many)).toHaveLength(20);
  });
});

describe('call import wrappers without the native module', () => {
  it('are safe no-ops', async () => {
    expect(entry.isAvailable()).toBe(false);
    expect(entry.isCallImportAvailable()).toBe(false);
    expect(entry.hasAudioReadPermission()).toBe(false);
    await expect(entry.listCallRecordings(0, 50)).resolves.toEqual([]);
    await expect(entry.getImportMeta('a.m4a')).resolves.toBeNull();
    await expect(entry.copyToAppStorage('content://media/external/audio/media/1', 'x.m4a')).rejects.toMatchObject({ code: 'ERR_UNAVAILABLE' });
    expect(entry.removeImport('a.m4a')).toBe(false);
    expect(() => entry.clearImports()).not.toThrow();
    expect(['android.permission.READ_MEDIA_AUDIO', 'android.permission.READ_EXTERNAL_STORAGE']).toContain(entry.audioReadPermission());
  });

  it('nativeEntry re-exports everything', () => {
    for (const fn of [
      'listCallRecordings',
      'copyToAppStorage',
      'hasAudioReadPermission',
      'audioReadPermission',
      'getImportMeta',
      'removeImport',
      'clearImports',
      'isCallImportAvailable',
      'parseImportFiles',
      'contentTypeFor',
      'isImportFileName',
    ]) {
      expect([fn, typeof ne[fn]]).toEqual([fn, 'function']);
    }
    expect(ne.IMPORTS_DIR).toBe('imports');
  });
});

describe('wrappers with a fake native module', () => {
  it('normalizes rows and maps error codes', async () => {
    jest.resetModules();
    const fake = {
      listCallRecordings: jest.fn(async () => [
        {
          uri: 'content://media/external/audio/media/7',
          displayName: 'Call recording +998901234567_241010_143012.m4a',
          relativePath: 'Recordings/Call/',
          sizeBytes: 1000,
          durationMs: 60000,
          dateMs: 1728560000000,
          mimeType: 'audio/mp4',
          contentType: 'audio/mp4',
        },
        { uri: 'file:///etc/passwd', displayName: 'x' },
        null,
        { uri: 'content://media/external/audio/media/8', displayName: 'a.mp3', sizeBytes: -5, durationMs: 'x', mimeType: 'audio/mpeg', contentType: null },
      ]),
      copyToAppStorage: jest.fn(async () => {
        throw Object.assign(new Error('file is too large'), { code: 'ERR_TOO_LARGE' });
      }),
      getImportMeta: jest.fn(async () => ({
        fileName: 'a.m4a',
        path: '/data/user/0/x/files/imports/a.m4a',
        displayName: 'Алишер.m4a',
        contentType: 'audio/mp4',
        sizeBytes: 5,
        durationMs: 3,
        dateMs: null,
        source: 'share',
      })),
      hasAudioReadPermission: () => true,
    };
    jest.doMock('expo', () => ({ requireOptionalNativeModule: () => fake }));
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const e2 = require('../modules/venera-entry') as typeof entry;
    expect(e2.isCallImportAvailable()).toBe(true);
    expect(e2.hasAudioReadPermission()).toBe(true);
    const rows = await e2.listCallRecordings(-1, 9999);
    expect(fake.listCallRecordings).toHaveBeenCalledWith(0, 500);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ relativePath: 'Recordings/Call/', contentType: 'audio/mp4', durationMs: 60000 });
    expect(rows[1]).toMatchObject({ sizeBytes: 0, durationMs: 0, contentType: null });
    await expect(e2.copyToAppStorage('content://x/1', 'a.m4a')).rejects.toMatchObject({ code: 'ERR_TOO_LARGE', message: 'file is too large' });
    await expect(e2.getImportMeta('a.m4a')).resolves.toMatchObject({ displayName: 'Алишер.m4a', dateMs: null, contentType: 'audio/mp4' });
    await expect(e2.getImportMeta('../a.m4a')).resolves.toBeNull();
  });
});

describe('native manifest and Kotlin rules', () => {
  const manifest = read('android/src/main/AndroidManifest.xml');
  const kt = read('android/src/main/java/uz/brbtech/venera/entry/VeneraEntryModule.kt');
  const callImport = read('android/src/main/java/uz/brbtech/venera/entry/CallImport.kt');

  it('declares ImportActivity (audio shares only) and both read permissions', () => {
    const m = /<activity[^>]*android:name="uz\.brbtech\.venera\.entry\.ImportActivity"[\s\S]*?<\/activity>/.exec(manifest);
    expect(m).not.toBeNull();
    const a = m![0];
    for (const s of [
      'android:exported="true"',
      'android:noHistory="true"',
      'android:excludeFromRecents="true"',
      'Theme.Translucent',
      'android.intent.action.SEND"',
      'android.intent.action.SEND_MULTIPLE"',
      'android:mimeType="audio/*"',
      'android.intent.category.DEFAULT',
    ]) {
      expect(a).toContain(s);
    }
    expect(a).not.toContain('video/');
    expect(manifest).toContain('<uses-permission android:name="android.permission.READ_MEDIA_AUDIO" />');
    expect(manifest).toMatch(/READ_EXTERNAL_STORAGE"\s+android:maxSdkVersion="32"/);
    for (const fn of ['listCallRecordings', 'copyToAppStorage', 'hasAudioReadPermission', 'getImportMeta', 'removeImport', 'clearImports']) {
      expect(kt).toContain(`"${fn}"`);
    }
  });

  it('CallImport.kt keeps its safety rules', () => {
    // "content://0@<o'z provayderimiz>" orqali shaxsiy fayllarni nusxalatib bo'lmasin.
    expect(callImport).toMatch(/uri\.userInfo != null \|\| authority\.contains\('@'\)/);
    // Import havolasi o'rnatish kalitini tarqatmaydi.
    expect(callImport).not.toMatch(/append\("&k="\)/);
    // Bitta nusxa server chegarasiga yaqin (150 MB), imports/ eskilari tozalanadi, mazmun tekshiriladi.
    expect(callImport).toContain('MAX_COPY_BYTES = 160L * 1024 * 1024');
    expect(callImport).toContain('removeStale(dir, System.currentTimeMillis())');
    expect(callImport).toContain('checkHeader = true');
    // Papka qoliplari boshidan bog'langan - "Download/call/" qo'ng'iroq bo'lib chiqmasin.
    expect(callImport).toContain('arrayOf("Recordings/Call/%", "Call/%")');
    expect(callImport).not.toMatch(/arrayOf\([^)]*"%\/Call\/%"/);
  });

  it('the native toast promises no size it cannot keep, in every shipped language', () => {
    for (const dir of ['values', 'values-ru', 'values-en']) {
      const xml = read(`android/src/main/res/${dir}/strings.xml`);
      expect([dir, /venera_entry_import_unsupported/.test(xml)]).toEqual([dir, true]);
      expect([dir, /400/.test(xml)]).toEqual([dir, false]);
    }
  });
});
