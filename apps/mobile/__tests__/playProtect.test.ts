/**
 * Google Play Protect regressiya qo'riqchisi (ega qarori, 2026-11-09): 1.3.5 sideload'da
 * "App not installed" bo'ldi - sababi "Maxsus imkoniyatlar" xizmati (ovoz tugmasi bilan yozish).
 * "Kuchaytirilgan firibgarlikdan himoya" shunday xizmat, bildirishnoma tinglovchisi, SMS va
 * qo'ng'iroqlar jurnali ruxsatlari bor ilovani o'rnatishning o'zida to'sadi.
 *
 * Bu test yiqilsa: (a) modules/ da shunday xizmat yoki uning izi qaytgan, (b) ilova shunday
 * ruxsat so'rayapti, (c) app.config `blockedPermissions` ro'yxatidan himoya ruxsati tushib qolgan
 * (yoki aksincha - ishlatiladigan ruxsat bloklangan).
 */
import { readdirSync, readFileSync, statSync } from 'fs';
import { join } from 'path';

const MODULES = join(__dirname, '..', 'modules');

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const files = walk(MODULES);
/** XML izohlari tashlanadi - izohdagi tarix matni qo'riqchini aldamasin. */
const xml = (p: string) => readFileSync(p, 'utf8').replace(/<!--[\s\S]*?-->/g, '');
const manifests = files.filter((p) => p.endsWith('AndroidManifest.xml'));

/** Play Protect sideload'da to'sadigan yoki keskin shubha uyg'otadigan ruxsatlar (step 2). */
const PLAY_PROTECT_BLOCKED = [
  'android.permission.RECEIVE_SMS',
  'android.permission.READ_SMS',
  'android.permission.SEND_SMS',
  'android.permission.RECEIVE_MMS',
  'android.permission.RECEIVE_WAP_PUSH',
  'android.permission.READ_CALL_LOG',
  'android.permission.WRITE_CALL_LOG',
  'android.permission.PROCESS_OUTGOING_CALLS',
  'android.permission.REQUEST_INSTALL_PACKAGES',
  'android.permission.QUERY_ALL_PACKAGES',
];
/** Xizmatni "himoyalaydigan" bog'lanish ruxsatlari - ularni so'rash ham, e'lon qilish ham taqiqlangan. */
const SENSITIVE_BINDS = ['android.permission.BIND_ACCESSIBILITY_SERVICE', 'android.permission.BIND_NOTIFICATION_LISTENER_SERVICE'];
/** Ilova ishlatadigan ruxsatlar - bloklansa yozish/yuklash/qo'ng'iroq importi buziladi. */
const MUST_KEEP = [
  'android.permission.RECORD_AUDIO',
  'android.permission.FOREGROUND_SERVICE',
  'android.permission.FOREGROUND_SERVICE_MICROPHONE',
  'android.permission.POST_NOTIFICATIONS',
  'android.permission.INTERNET',
  'android.permission.ACCESS_NETWORK_STATE',
  'android.permission.ACCESS_WIFI_STATE',
  'android.permission.WAKE_LOCK',
  'android.permission.RECEIVE_BOOT_COMPLETED',
  'android.permission.VIBRATE',
  'android.permission.MODIFY_AUDIO_SETTINGS',
  'android.permission.READ_MEDIA_AUDIO',
  'android.permission.READ_EXTERNAL_STORAGE',
];

function appConfig(variant?: string): { permissions: string[]; blocked: string[] } {
  const before = process.env.APP_VARIANT;
  if (variant) process.env.APP_VARIANT = variant;
  try {
    let make: (ctx: { config: object }) => { android: { permissions?: string[]; blockedPermissions?: string[] } };
    jest.isolateModules(() => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      make = require('../app.config').default;
    });
    const c = make!({ config: {} });
    return { permissions: c.android.permissions ?? [], blocked: c.android.blockedPermissions ?? [] };
  } finally {
    if (before === undefined) delete process.env.APP_VARIANT;
    else process.env.APP_VARIANT = before;
  }
}

describe('Play Protect guard', () => {
  it('(a) no Accessibility or notification-listener service anywhere in modules/ (manifest, resources, code)', () => {
    expect(manifests.length).toBeGreaterThan(0);
    for (const m of manifests) {
      const text = xml(m);
      for (const bind of SENSITIVE_BINDS) expect([m, text.includes(bind)]).toEqual([m, false]);
      expect([m, /android\.accessibilityservice/.test(text)]).toEqual([m, false]);
      expect([m, /android\.service\.notification\.NotificationListenerService/.test(text)]).toEqual([m, false]);
    }
    // Resurs (`<accessibility-service>` xml) va Kotlin klass ham qolmasin - manifestga qaytarish oson bo'lmasin.
    for (const f of files.filter((p) => p.endsWith('.xml'))) expect([f, /<accessibility-service\b/.test(xml(f))]).toEqual([f, false]);
    for (const f of files.filter((p) => /\.(kt|java)$/.test(p))) {
      const code = readFileSync(f, 'utf8');
      expect([f, /\b(AccessibilityService|NotificationListenerService)\b|ACCESSIBILITY_SETTINGS|ENABLED_ACCESSIBILITY_SERVICES/.test(code)]).toEqual([f, false]);
    }
  });

  it('(a) the volume-key bindings are gone from the module JS wrapper too', () => {
    const wrapper = readFileSync(join(MODULES, 'venera-entry', 'index.ts'), 'utf8');
    expect(wrapper).not.toMatch(/isKeyServiceEnabled|openAccessibilitySettings/);
    for (const f of files.filter((p) => p.endsWith('strings.xml'))) expect([f, xml(f).includes('venera_entry_key_service')]).toEqual([f, false]);
  });

  it('(b) neither the app config nor any module manifest requests a sensitive permission', () => {
    for (const variant of ['production', 'development']) {
      const { permissions } = appConfig(variant);
      for (const p of [...PLAY_PROTECT_BLOCKED, ...SENSITIVE_BINDS, 'android.permission.SYSTEM_ALERT_WINDOW']) {
        expect([variant, p, permissions.includes(p)]).toEqual([variant, p, false]);
      }
    }
    for (const m of manifests) {
      const used = [...xml(m).matchAll(/<uses-permission[^>]*android:name="([^"]+)"/g)].map((x) => x[1]);
      for (const p of [...PLAY_PROTECT_BLOCKED, ...SENSITIVE_BINDS]) expect([m, p, used.includes(p)]).toEqual([m, p, false]);
    }
  });

  it('(c) blockedPermissions keeps every Play Protect entry and the audited unused ones - and never a needed one', () => {
    const { permissions, blocked } = appConfig();
    for (const p of PLAY_PROTECT_BLOCKED) expect([p, blocked.includes(p)]).toEqual([p, true]);
    for (const p of [
      'android.permission.SYSTEM_ALERT_WINDOW',
      'android.permission.WRITE_EXTERNAL_STORAGE',
      'android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK',
      'android.permission.USE_BIOMETRIC',
      'android.permission.USE_FINGERPRINT',
      'com.google.android.finsky.permission.BIND_GET_INSTALL_REFERRER_SERVICE',
    ]) {
      expect([p, blocked.includes(p)]).toEqual([p, true]);
    }
    // Ortiqcha bloklash ham xato: tools:node="remove" ishlatiladigan ruxsatni ham o'chiradi.
    for (const p of MUST_KEEP) expect([p, blocked.includes(p)]).toEqual([p, false]);
    // So'ralgan ruxsat bir vaqtda bloklanmagan bo'lsin (aks holda yozish jim buziladi).
    for (const p of permissions) expect([p, blocked.includes(p)]).toEqual([p, false]);
  });
});
