// Standart Expo babel sozlamasi. NIMA UCHUN fayl bor: jest-expo'ning platforma
// presetlari (jest-expo/android) babel sozlamasini loyiha faylidan oladi -
// usiz React Native'ning Flow kodi Jest'da parse bo'lmaydi. Metro uchun
// natija Expo default'i bilan bir xil.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
  };
};
