import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// CORS-free dev fallback: when VITE_API_BASE is left empty in .env, the fetch
// call uses a relative URL and Vite forwards `/api` to the Spring Boot backend.
// When VITE_API_BASE is set to an absolute URL, the proxy is unused and the
// browser calls Spring Boot directly (the backend must allow this origin).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || env.VITE_API_BASE || 'http://10.10.50.9:8080'
  const proxy = { '/api': target }
  return {
    plugins: [vue()],
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
    build: { cssMinify: 'lightningcss' },
  }
})
