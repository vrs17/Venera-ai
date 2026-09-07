// Swagger UI ni ishga tushirish.
//
// NEGA ALOHIDA FAYL, HTML ichida emas: frontend nginx butun saytga qattiq CSP
// qo'yadi - `script-src 'self'`. Bu INLINE `<script>` blokini bloklaydi.
// FastAPI ning tayyor `get_swagger_ui_html()` funksiyasi esa aynan inline blok
// yozadi, natijada `swagger-ui-bundle.js` yuklanardi-yu, uni ISHGA TUSHIRADIGAN
// kod bloklanardi va sahifa BO'SH ochilardi. curl buni ko'rmaydi - u JS
// ishlatmaydi, shuning uchun 200 qaytardi.
//
// Yechim: kodni tashqi faylga chiqarish. Shunda CSP ni bo'shashtirish
// (`'unsafe-inline'` qo'shish) KERAK EMAS - u butun sayt uchun ochilardi.
window.ui = SwaggerUIBundle({
  url: "/api/openapi.json",
  dom_id: "#swagger-ui",
  layout: "BaseLayout",
  deepLinking: true,
  showExtensions: true,
  showCommonExtensions: true,
  // `SwaggerUIStandalonePreset` ATAYLAB yo'q: u alohida faylda
  // (swagger-ui-standalone-preset.js) va biz uni yuklamaymiz. FastAPI ning
  // shabloni unga murojaat qiladi va `undefined` uzatadi - bu ishlaydi, lekin
  // yozilgani xato. Bizga faqat API ro'yxati kerak.
  presets: [SwaggerUIBundle.presets.apis],
});
