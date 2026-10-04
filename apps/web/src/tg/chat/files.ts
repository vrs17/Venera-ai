// Fayllarni Telegram ichida ochish: imzolangan qisqa havola -> Telegram yuklab olgichi
// yoki tashqi brauzer.
//
// NEGA `<a download>` EMAS (web'dagi kabi). Telegram WebView'da `blob:` bilan yuklab olish
// ishonchsiz (iOS umuman bajarmaydi), Telegram'ning o'z yuklab olgichi (`downloadFile`)
// va tashqi brauzer (`openLink`) esa bizning `Authorization` sarlavhamizni yubora
// olmaydi. Shuning uchun server avval sessiya bilan 10 daqiqalik IMZOLANGAN havola
// beradi (`POST .../link`), Telegram faylni shu havoladan tokensiz oladi.
//
//   ariza (DOCX/PDF)    POST /api/v1/chat/artifact/{token}/{kind}/link
//   iqtibos hujjati     POST /api/v1/chat/doc/{doc_id}/link
//                       (javob ariza havolasi bilan bir xil: {url, filename, expiresIn};
//                       PDF tashqi brauzerda `inline` ochiladi - o'qish uchun, saqlash emas)

import { downloadFile as webDownload } from '../../api/chat.api'
import { ApiError, apiFetch } from '../../api/http'
import { downloadFile, isTelegram, openLink } from '../telegram'

interface FileLink {
  url: string
  filename: string
  expiresIn: number
}

export type OpenOutcome = 'opened' | 'unsupported'

function absolute(path: string): string {
  return new URL(path, location.origin).href
}

/** Ariza fayli: Telegram yuklab olgichi (saqlash oynasi), eski klientda - tashqi
 *  brauzer (u `Content-Disposition: attachment` bo'yicha o'zi saqlaydi). */
export async function saveArtifact(path: string, name: string): Promise<void> {
  const link = await apiFetch<FileLink>(`${path}/link`, { method: 'POST', body: JSON.stringify({ filename: name }) })
  const url = absolute(link.url)
  if (!downloadFile(url, link.filename)) openLink(url)
}

/** Iqtibos qilingan hujjat (PDF): imzolangan havola tashqi brauzerda - u PDF'ni
 *  o'zi ko'rsatadi (Mini App'da pdf.js yo'q - bundle yengil bo'lsin). Server 400
 *  (kalit yaroqsiz) bersa - xato, ekran toast ko'rsatadi. 404/405/501 faqat eski
 *  backend'da (endpoint yo'q): Telegram'dan tashqarida (stub) web'dagi kabi sessiya
 *  bilan yuklab olinadi; Telegram ichida - `unsupported`, "veb ilovada oching". */
export async function openCitedDoc(docId: string, docUrl: string | null | undefined, name: string): Promise<OpenOutcome> {
  try {
    const link = await apiFetch<FileLink>(`/api/v1/chat/doc/${encodeURIComponent(docId)}/link`, {
      method: 'POST',
      body: JSON.stringify({ filename: name }),
    })
    if (link?.url) {
      openLink(absolute(link.url))
      return 'opened'
    }
  } catch (err) {
    const missing = err instanceof ApiError && (err.status === 404 || err.status === 405 || err.status === 501)
    if (!missing) throw err
  }
  if (!isTelegram && docUrl) {
    await webDownload(docUrl.split('#')[0], `${name || 'hujjat'}.pdf`)
    return 'opened'
  }
  return 'unsupported'
}
