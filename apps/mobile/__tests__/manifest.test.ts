/**
 * Statik tekshiruv (spec 8.2): venera-entry manifesti launcher activity
 * (o'chirilgan, MAIN/LAUNCHER) va plitka xizmatini (BIND_QUICK_SETTINGS_TILE,
 * QS_TILE) e'lon qiladi; Kotlin klasslari va JS nomlari bir-biriga mos.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

const MOD = join(__dirname, '..', 'modules', 'venera-entry');
const read = (p: string) => readFileSync(join(MOD, p), 'utf8');
const manifest = read('android/src/main/AndroidManifest.xml');

function block(tag: string, name: string): string {
  const re = new RegExp(`<${tag}[^>]*android:name="uz\\.brbtech\\.venera\\.entry\\.${name}"[\\s\\S]*?</${tag}>`);
  const m = re.exec(manifest);
  if (!m) throw new Error(`${tag} ${name} topilmadi`);
  return m[0];
}

describe('venera-entry native module', () => {
  it('declares the disabled "Yozish" launcher activity', () => {
    const a = block('activity', 'RecordLauncherActivity');
    expect(a).toContain('android:enabled="false"');
    expect(a).toContain('android:exported="true"');
    expect(a).toContain('android:excludeFromRecents="true"');
    expect(a).toContain('android:noHistory="true"');
    expect(a).toContain('Theme.Translucent');
    expect(a).toContain('<action android:name="android.intent.action.MAIN" />');
    expect(a).toContain('<category android:name="android.intent.category.LAUNCHER" />');
  });

  it('declares the Quick Settings tile service', () => {
    const s = block('service', 'RecordTileService');
    expect(s).toContain('android:permission="android.permission.BIND_QUICK_SETTINGS_TILE"');
    expect(s).toContain('<action android:name="android.service.quicksettings.action.QS_TILE" />');
    expect(s).toContain('android:exported="true"');
  });

  it('Kotlin sources, module config and JS wrapper agree', () => {
    const cfg = JSON.parse(read('expo-module.config.json'));
    expect(cfg.android.modules).toEqual(['uz.brbtech.venera.entry.VeneraEntryModule']);
    const kt = read('android/src/main/java/uz/brbtech/venera/entry/VeneraEntryModule.kt');
    expect(kt).toContain('Name("VeneraEntry")');
    for (const fn of ['setRecordingState', 'requestAddTile', 'setLauncherEnabled', 'isLauncherEnabled', 'setTrustedKey']) {
      expect(kt).toContain(`"${fn}"`);
      expect(read('index.ts')).toContain(`export ${fn === 'requestAddTile' ? 'async function' : 'function'} ${fn}`);
    }
    expect(read('index.ts')).toContain("requireOptionalNativeModule<VeneraEntryNative>('VeneraEntry')");
    const tile = read('android/src/main/java/uz/brbtech/venera/entry/RecordTileService.kt');
    expect(tile).toContain('unlockAndRun');
    expect(tile).toContain('PendingIntent.FLAG_IMMUTABLE');
    expect(kt).toContain('scheme("venera-rec")');
    expect(kt).toContain('setPackage(ctx.packageName)');
    expect(read('android/build.gradle')).toContain('namespace "uz.brbtech.venera.entry"');
  });

  it('.gitignore hides only the generated root android/ios, not the Kotlin module', () => {
    const lines = readFileSync(join(__dirname, '..', '.gitignore'), 'utf8').split('\n').map((l) => l.trim());
    expect(lines).toContain('/android/');
    expect(lines).toContain('/ios/');
    expect(lines).not.toContain('android/');
  });

  it('JS wrapper is a no-op without the native module (Jest / iOS / escape hatch)', async () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const entry = require('../modules/venera-entry') as typeof import('../modules/venera-entry');
    expect(entry.isAvailable()).toBe(false);
    expect(() => entry.setRecordingState(true)).not.toThrow();
    expect(() => entry.setTrustedKey('k')).not.toThrow();
    expect(entry.isLauncherEnabled()).toBe(false);
    await expect(entry.requestAddTile()).resolves.toBe('unsupported');
  });
});

describe('app config', () => {
  it('sets scheme, package, backup off, blocked permissions and the FGS-enabling plugins', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const make = require('../app.config').default as (ctx: { config: object }) => Record<string, any>;
    const c = make({ config: {} });
    // Mahsulot nomi "Barno" (launcher); texnik nomlar (sxema, paket) o'zgarmaydi.
    expect(c.name).toBe('Barno');
    expect(c.scheme).toBe('venera-rec');
    expect(c.android.package).toBe('uz.brbtech.venera.meetings');
    expect(c.android.allowBackup).toBe(false);
    // Google Play build'i (BARNO_PLAY=1) - alohida package; qolgani (nom, sxema) o'sha.
    process.env.BARNO_PLAY = '1';
    try {
      jest.isolateModules(() => {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const play = (require('../app.config').default as typeof make)({ config: {} });
        expect(play.android.package).toBe('uz.brbtech.barno');
        expect(play.scheme).toBe('venera-rec');
        expect(play.name).toBe('Barno');
      });
    } finally {
      delete process.env.BARNO_PLAY;
    }
    expect(c.android.blockedPermissions).toEqual(
      expect.arrayContaining(['android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK', 'android.permission.SYSTEM_ALERT_WINDOW']),
    );
    // Qo'ng'iroq yozuvlari Android 8-12 da READ_EXTERNAL_STORAGE (maxSdk 32) bilan o'qiladi -
    // bloklansa tools:node="remove" venera-entry e'lonini ham o'chiradi. Yozish ruxsati esa bloklangan qoladi.
    expect(c.android.blockedPermissions).not.toContain('android.permission.READ_EXTERNAL_STORAGE');
    expect(c.android.blockedPermissions).toContain('android.permission.WRITE_EXTERNAL_STORAGE');
    const audio = c.plugins.find((p: unknown) => Array.isArray(p) && p[0] === 'expo-audio');
    expect(audio[1]).toMatchObject({ enableBackgroundRecording: true, enableBackgroundPlayback: false, recordAudioAndroid: true });
    const bp = c.plugins.find((p: unknown) => Array.isArray(p) && p[0] === 'expo-build-properties');
    expect(bp[1].android).toMatchObject({ compileSdkVersion: 36, targetSdkVersion: 36, minSdkVersion: 26 });
    expect(bp[1].android.usesCleartextTraffic).toBeUndefined(); // prod: faqat HTTPS
    expect(c.extra.apiBaseUrl).toBe('https://llm.brb-tech.uz');
    // Mini App (asosiy ekran) - default shu serverning /tg/ i.
  });
});
