/**
 * plugins/withReleaseSigning.js: release faqat o'z kalitimiz bilan imzolanadi,
 * kalit yo'q bo'lsa release yig'ish to'xtaydi; prebuild --clean dan keyin ham
 * (har prebuild'da qo'shiladi) va ikki marta qo'shilmaydi.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const plugin = require('../plugins/withReleaseSigning') as { addReleaseSigning(s: string): string; MARKER: string };

// Expo SDK 57 shablonidagi release qismi (debug kalit bilan imzolaydi).
const TEMPLATE = `android {
    signingConfigs {
        debug {
            storeFile file('debug.keystore')
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.debug
        }
    }
}
`;

describe('release signing config plugin', () => {
  it('appends a release signingConfig from ~/.gradle properties and a guard, once', () => {
    const out = plugin.addReleaseSigning(TEMPLATE);
    expect(out.startsWith(TEMPLATE.trimEnd())).toBe(true);
    expect(out).toContain(plugin.MARKER);
    for (const k of ['VENERA_STORE_FILE', 'VENERA_STORE_PASSWORD', 'VENERA_KEY_ALIAS', 'VENERA_KEY_PASSWORD']) expect(out).toContain(`'${k}'`);
    expect(out).toContain('signingConfig signingConfigs.veneraRelease');
    expect(out).toMatch(/\(assemble\|bundle\|package\|install\)Release/);
    expect(out).toContain("project.hasProperty('veneraAllowDebugSigned')");
    expect(out).toContain('throw new GradleException(');
    // Google Play (2026-11-19): `-PbarnoPlayUpload=true` - Play upload kaliti; APK kaliti (VENERA_*) o'zgarmaydi.
    expect(out).toContain("project.hasProperty('barnoPlayUpload')");
    for (const k of ['BARNO_UPLOAD_STORE_FILE', 'BARNO_UPLOAD_STORE_PASSWORD', 'BARNO_UPLOAD_KEY_ALIAS', 'BARNO_UPLOAD_KEY_PASSWORD']) expect(out).toContain(`'${k}'`);
    expect(out).toContain('Barno Play: upload kaliti yo');
    expect(plugin.addReleaseSigning(out)).toBe(out);
    // Groovy qavslari muvozanatda.
    const count = (c: string) => out.split(c).length - 1;
    expect(count('{')).toBe(count('}'));
    expect(count('(')).toBe(count(')'));
  });

  it('is registered in app.config.ts', () => {
    const cfg = readFileSync(join(__dirname, '..', 'app.config.ts'), 'utf8');
    expect(cfg).toContain("'./plugins/withReleaseSigning'");
  });
});
