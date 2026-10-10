// Metro standart Expo sozlamasi bilan ishlaydi. Alohida fayl faqat keyinchalik
// qo'shimcha (masalan, .aac assetlar) kerak bo'lsa joy bo'lishi uchun turibdi.
// Babel: babel.config.js faqat babel-preset-expo (reanimated kabi plagin yo'q).
const { getDefaultConfig } = require('expo/metro-config');

module.exports = getDefaultConfig(__dirname);
