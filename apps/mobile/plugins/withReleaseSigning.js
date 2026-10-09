/**
 * Release APK imzosi (README 4-bo'lim) - `expo prebuild --clean` dan keyin ham qoladi.
 *
 * NIMA UCHUN: Expo shabloni `android/app/build.gradle` da release'ni DEBUG
 * kalit bilan imzolaydi - `assembleRelease` "ishlaydigan" APK beradi. Shunday
 * APK pilotga ketsa, keyingi to'g'ri imzolangan yangilanish "imzo mos emas"
 * bilan o'rnatilmaydi; o'chirib qayta o'rnatish esa telefondagi hali
 * yuklanmagan yozuvlarni o'chiradi.
 *
 * Shuning uchun: `~/.gradle/gradle.properties` da VENERA_STORE_FILE,
 * VENERA_STORE_PASSWORD, VENERA_KEY_ALIAS, VENERA_KEY_PASSWORD bo'lsa release
 * shu kalit bilan imzolanadi; bo'lmasa release yig'ish XATO bilan to'xtaydi.
 * Faqat o'zingiz sinash uchun: `-PveneraAllowDebugSigned=true` (bunday APK
 * pilotga berilmaydi). Debug/dev client'ga ta'sir qilmaydi.
 *
 * Shablon matniga tayanmaydi: build.gradle oxiriga ikkinchi `android {}`
 * bloki qo'shiladi (Gradle bir xil kengaytmani qayta sozlaydi va release
 * `signingConfig` ni almashtiradi). Marker bilan idempotent.
 */
const { withAppBuildGradle } = require('expo/config-plugins');

const MARKER = '// @venera-release-signing';

const BLOCK = `
${MARKER} (plugins/withReleaseSigning.js) - prebuild har safar qayta qo'shadi.
def veneraReleaseProps = ['VENERA_STORE_FILE', 'VENERA_STORE_PASSWORD', 'VENERA_KEY_ALIAS', 'VENERA_KEY_PASSWORD']
def veneraHasReleaseKey = veneraReleaseProps.every { project.hasProperty(it) }
android {
    signingConfigs {
        if (veneraHasReleaseKey) {
            veneraRelease {
                storeFile file(project.property('VENERA_STORE_FILE'))
                storePassword project.property('VENERA_STORE_PASSWORD')
                keyAlias project.property('VENERA_KEY_ALIAS')
                keyPassword project.property('VENERA_KEY_PASSWORD')
            }
        }
    }
    buildTypes {
        release {
            if (veneraHasReleaseKey) {
                signingConfig signingConfigs.veneraRelease
            }
        }
    }
}
gradle.taskGraph.whenReady { graph ->
    def wantsRelease = graph.allTasks.any { t -> t.project == project && t.name ==~ /(assemble|bundle|package|install)Release/ }
    if (wantsRelease && !veneraHasReleaseKey && !project.hasProperty('veneraAllowDebugSigned')) {
        throw new GradleException("Venera: release kaliti yo'q (VENERA_STORE_FILE, VENERA_STORE_PASSWORD, VENERA_KEY_ALIAS, VENERA_KEY_PASSWORD - ~/.gradle/gradle.properties). README 4-bo'lim. Faqat o'zingiz sinash uchun: -PveneraAllowDebugSigned=true - bunday APK'ni pilotga BERMANG.")
    }
}
`;

/** build.gradle matniga blokni qo'shish (toza funksiya - Jest tekshiradi). */
function addReleaseSigning(contents) {
  if (contents.includes(MARKER)) return contents;
  return `${contents.replace(/\s*$/, '')}\n${BLOCK}`;
}

function withReleaseSigning(config) {
  return withAppBuildGradle(config, (c) => {
    if (c.modResults.language !== 'groovy') {
      throw new Error('withReleaseSigning: faqat Groovy build.gradle qo\'llab-quvvatlanadi');
    }
    c.modResults.contents = addReleaseSigning(c.modResults.contents);
    return c;
  });
}

module.exports = withReleaseSigning;
module.exports.addReleaseSigning = addReleaseSigning;
module.exports.MARKER = MARKER;
