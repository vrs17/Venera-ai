// Telegram Mini App - kirish nuqtasi (tg-app.html).
//
// O'z `createApp` i: web ilovaning routeri, yon paneli, admin qismi va PDF ko'ruvchisi
// (pdf.js) bu bundle'ga KIRMAYDI. Ekranlar ichki holat mashinasi bilan almashadi
// (App.vue) - Mini App'da manzil satri yo'q, ya'ni router faqat og'irlik qo'shardi.
//
// Tartib muhim:
//   1. kanal (`X-Venera-Client: miniapp`) - birinchi so'rovdan OLDIN, aks holda
//      /auth/me "web" bo'lib yoziladi va dvigatel (`HRM_ASSISTANT_ENGINE_BY_CHANNEL`)
//      noto'g'ri tanlanadi. Qiymat umumiy API qatlamida (`api/http.ts`): apiFetch ham,
//      chat/tts'ning to'g'ridan-to'g'ri fetch'lari ham shuni o'qiydi;
//   2. Telegram (mavzu, xavfsiz zona) va ramka balandligi - birinchi chizishdan oldin;
//   3. `tg.*` matnlari - komponentlar ularni birinchi render'da o'qiydi.

import { createApp } from 'vue'
import '../tokens.css'
import '../styles/tokens.css'
import '../styles/base.css'
import './styles.css'
import { setClientChannel } from '../api/http'
import { i18n } from '../i18n'
import App from './App.vue'
import { installTgMessages } from './i18n'
import { startLayout } from './layout'
import { startTelegram } from './telegram'

setClientChannel('miniapp')
startTelegram()
startLayout()
installTgMessages()

createApp(App).use(i18n).mount('#root')
