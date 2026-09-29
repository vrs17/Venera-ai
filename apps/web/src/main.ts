import { createApp } from 'vue'
// Uslublar tartibi: desktop bilan umumiy (generatsiya qilingan) holat ranglari, keyin
// dizayn tokenlari (yagona manba), keyin asos (shrift, reset, tipografiya).
import './tokens.css'
import './styles/tokens.css'
import './styles/base.css'
import App from './App.vue'
import { i18n } from './i18n'
import { router } from './router'
import { initTheme } from './theme'

initTheme()

const app = createApp(App).use(i18n).use(router)

// Birinchi marshrut (va uning /auth/me tekshiruvi) tayyor bo'lguncha #root dagi
// yuklanish belgisi turadi: mount uni almashtiradi, ya'ni undan oldin bo'sh ekran
// bo'lmaydi. Navigatsiya xato bilan tugasa ham ilova baribir ochiladi.
const mount = () => app.mount('#root')
router.isReady().then(mount, mount)
