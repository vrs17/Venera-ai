import { createReadStream, existsSync, statSync } from 'node:fs'
import { basename, resolve } from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import type { Connect, Plugin, PreviewServer, ViteDevServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// Monorepo ildizidagi release/ papkasi — desktop .exe va version.json shu yerda.
const RELEASE_DIR = resolve(__dirname, '../../release')

/**
 * FAQAT dev/preview uchun: release/ papkasini /download/ ostida ko'rsatadi,
 * ya'ni production'dagi nginx (deploy/nginx.container.conf) qiladigan ishni
 * takrorlaydi.
 *
 * Busiz splash sahifadagi yuklab olish kartasi lokalda doim "mavjud emas"
 * holatida qolardi va oqimni ishga tushirmasdan tekshirib bo'lmasdi.
 *
 * Production bundle'ga TA'SIR QILMAYDI: `apply: 'serve'` sababli plugin
 * `vite build` paytida umuman ishlamaydi, .exe dist/ ga tushmaydi.
 */
function releaseDownloads(): Plugin {
  const handler: Connect.NextHandleFunction = (req, res, next) => {
    // connect '/download' prefiksini olib tashlaydi, req.url = '/version.json'.
    const requested = decodeURIComponent((req.url || '/').split('?')[0])
    const name = basename(requested)
    const file = resolve(RELEASE_DIR, name)

    // basename() papkadan chiqishga yo'l qo'ymaydi; startsWith ikkinchi to'siq.
    if (!name || !file.startsWith(RELEASE_DIR) || !existsSync(file)) return next()
    const stat = statSync(file)
    if (!stat.isFile()) return next()

    const isJson = name.endsWith('.json')
    res.setHeader('Content-Type', isJson ? 'application/json' : 'application/octet-stream')
    res.setHeader('Content-Length', String(stat.size))
    res.setHeader('Cache-Control', isJson ? 'no-store' : 'public, max-age=2592000')
    if (!isJson) res.setHeader('Content-Disposition', 'attachment')
    createReadStream(file).pipe(res)
  }

  return {
    name: 'venera-release-downloads',
    apply: 'serve',
    configureServer(server: ViteDevServer) {
      server.middlewares.use('/download', handler)
    },
    configurePreviewServer(server: PreviewServer) {
      server.middlewares.use('/download', handler)
    },
  }
}

// Telegram Mini App (`apps/tg/`) - ikkita fayl, build yo'q. Production'da
// uni nginx host'dan mount qilib `/tg/` ostida beradi
// (deploy/nginx.container.conf); dev serverda esa hech kim bermasdi, ya'ni
// Mini App'ni lokalda umuman ochib bo'lmasdi. Bu plugin o'sha ishni
// takrorlaydi: http://<host>:5174/tg/ - va `/api` o'sha proxy orqali ketadi.
//
// Production bundle'ga TA'SIR QILMAYDI (`apply: 'serve'`): fayllar dist/ ga
// tushmaydi - ular obrazga ham kirmaydi, host'dan mount qilinadi.
const TG_DIR = resolve(__dirname, '../tg')

function tgMiniApp(): Plugin {
  const handler: Connect.NextHandleFunction = (req, res, next) => {
    // nginx kabi: `/tg` -> `/tg/`, aks holda `app.js` ildizdan qidirilardi.
    if ((req.originalUrl || '').split('?')[0] === '/tg') {
      res.statusCode = 301
      res.setHeader('Location', '/tg/')
      res.end()
      return
    }
    // connect '/tg' prefiksini olib tashlaydi, req.url = '/' yoki '/app.js'.
    const requested = decodeURIComponent((req.url || '/').split('?')[0])
    const name = basename(requested) || 'index.html'
    const file = resolve(TG_DIR, name)

    if (!file.startsWith(TG_DIR) || !existsSync(file)) return next()
    const stat = statSync(file)
    if (!stat.isFile()) return next()

    const type = name.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : name.endsWith('.html') ? 'text/html; charset=utf-8'
      : 'application/octet-stream'
    res.setHeader('Content-Type', type)
    res.setHeader('Content-Length', String(stat.size))
    // Production'dagi `/tg/` javobi bilan bir xil: har so'rovda diskdan.
    res.setHeader('Cache-Control', 'no-cache')
    createReadStream(file).pipe(res)
  }

  return {
    name: 'venera-tg-mini-app',
    apply: 'serve',
    configureServer(server: ViteDevServer) {
      server.middlewares.use('/tg', handler)
    },
    configurePreviewServer(server: PreviewServer) {
      server.middlewares.use('/tg', handler)
    },
  }
}

// Yangi Telegram Mini App (tg-app.html -> src/tg/, web kod bazasida) - hozircha BETA:
// `/tg-beta/` ostida, sinovchilar uni botdagi /beta orqali ochadi. Eski ilova
// (yuqoridagi plugin, `apps/tg`) almashtirish tasdiqlanguncha `/tg/` da qoladi.
//
// Mini App'ga oid ikki ish BITTA plugin'da - keyin `/tg/` ga ko'chirish yoki olib
// tashlash shu yerda va nginx'dagi bitta location'da bo'ladi:
//   build       - ikkinchi kirish nuqtasi: dist/ ga index.html bilan birga tg-app.html
//                 yig'iladi. Mini App o'z bo'laklari bilan - web'ning routeri, admin
//                 qismi va pdf.js unga kirmaydi; umumiy kod (Vue, i18n, API) /assets/
//                 dagi umumiy bo'laklarda, ikkala sahifa ularni bitta keshdan oladi.
//   dev/preview - `/tg-beta/...` so'rovi `/tg-app.html` ga qayta yoziladi (nginx'dagi
//                 `try_files /tg-app.html` kabi). Dev'da sahifani Vite o'zi o'zgartiradi,
//                 ya'ni HMR ham ishlaydi; preview'da dist/tg-app.html beriladi.
const TG_BETA_PATH = '/tg-beta'
const TG_APP_HTML = '/tg-app.html'

function tgBetaApp(): Plugin {
  const handler: Connect.NextHandleFunction = (req, res, next) => {
    const path = (req.url || '').split('?')[0]
    // nginx kabi: `/tg-beta` -> `/tg-beta/`.
    if (path === TG_BETA_PATH) {
      res.statusCode = 301
      res.setHeader('Location', `${TG_BETA_PATH}/`)
      res.end()
      return
    }
    // Ichki holat mashinasi, router yo'q: `/tg-beta/` ostidagi har qanday yo'l bitta
    // sahifa. So'rov satri serverga kerak emas: dev stub uni brauzerdagi
    // `location.search` dan o'qiydi (src/tg/telegram.ts).
    if (path.startsWith(`${TG_BETA_PATH}/`)) req.url = TG_APP_HTML
    next()
  }

  return {
    name: 'venera-tg-beta-app',
    config: () => ({
      build: {
        rolldownOptions: {
          input: {
            // `index` - web kirish nuqtasining bo'lak nomi avvalgidek qoladi.
            index: resolve(__dirname, 'index.html'),
            tg: resolve(__dirname, 'tg-app.html'),
          },
        },
      },
    }),
    // Prefikssiz `use(handler)` - `use('/tg-beta', ...)` EMAS: connect prefiksli
    // middleware'dan keyin `req.url` ga prefiksni QAYTA yopishtiradi, ya'ni qayta
    // yozilgan yo'l `/tg-beta/tg-app.html` bo'lib qolardi.
    configureServer(server: ViteDevServer) {
      server.middlewares.use(handler)
    },
    configurePreviewServer(server: PreviewServer) {
      server.middlewares.use(handler)
    },
  }
}

// CORS-free dev fallback: when VITE_API_BASE is left empty in .env, the fetch
// call uses a relative URL and Vite forwards `/api` to the Spring Boot backend.
// When VITE_API_BASE is set to an absolute URL, the proxy is unused and the
// browser calls Spring Boot directly (the backend must allow this origin).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || env.VITE_API_BASE || 'http://10.10.50.9:8080'
  const proxy = { '/api': target }
  return {
    plugins: [vue(), releaseDownloads(), tgMiniApp(), tgBetaApp()],
    // host: true binds 0.0.0.0 so the dev server is reachable on the LAN
    // (http://<your-ip>:5173). Pinned port keeps the URL + firewall rule stable.
    server: { host: true, port: 5173, proxy },
    // `vite preview` serves the built dist/ (production bundle). It needs the same
    // /api proxy as the dev server, and allowedHosts: true because it runs behind a
    // trusted reverse proxy that forwards the public domain in the Host header.
    preview: { proxy, allowedHosts: true },
    // Use lightningcss for CSS minification instead of esbuild's. Esbuild was
    // collapsing the paired `backdrop-filter` / `-webkit-backdrop-filter`
    // declarations down to just the prefixed one, which weakened the glass blur
    // in production. lightningcss honours browserslist and keeps both prefixes.
    build: {
      cssMinify: 'lightningcss',
      // Shriftlar HECH QACHON `data:` URL bo'lib CSS ichiga tikilmaydi. Vite 4 KB dan
      // kichik fayllarni base64 qilib qo'yadi, va JetBrains Mono'ning 2 KB lik
      // cyrillic-ext bo'lagi shunday bo'lib qolgan edi - prod CSP (`font-src 'self'`)
      // uni bloklardi va Қ/Ғ/Ҳ boshqa shriftda chiqardi. CSP'ga `data:` qo'shish
      // o'rniga fayl o'z URL'i bilan beriladi: siyosat qattiqligicha qoladi.
      // Boshqa fayllar uchun `undefined` - Vite'ning odatiy chegarasi ishlayveradi.
      assetsInlineLimit: (filePath: string) => (/\.(woff2?|ttf|otf|eot)$/i.test(filePath) ? false : undefined),
    },
  }
})
