// Javob HTML'ining Mini App uchun "pardozi" - MarkdownMessage chizgandan KEYIN, DOM
// ustida (u umumiy komponent, web bilan bir xil - unga tegmaymiz).
//
//   1. `[T1]` chipi -> tizim nomi ("HRM" / "CRM"). Asl belgi `data-marker` da qoladi:
//      chip bosilganda manbalar oynasi aynan o'sha so'rovni belgilaydi.
//   2. SO'Z + CHIP + TINISH BELGISI bitta `nowrap` bo'lakka: tor ekranda "7 kun ⏎ [2] ."
//      kabi chip yoki nuqta yangi qatorga yolg'iz tushmaydi.
//   3. O'ZBEKCHA TUTUQ BELGILARI (faqat lotin): model `'` yozadi, interfeys esa `ʻ`/`ʼ`
//      - bir ekranda "koʻpi" va "ko'ra" yonma-yon chiqmasin. o'/g' -> ʻ, qolgan
//      harf'harf -> ʼ. Kod, havola va chip ichiga tegilmaydi.
//
// Har o'tish idempotent: oqim paytida MarkdownMessage HTML'ni har kadrda qayta
// yozadi va bu funksiya yangi DOM ustida qayta ishlaydi.

const SKIP = 'code, pre, a, .vmd-cite, .tg-glue'
const TRAILING = /^[.,;:!?)\]»”…]+/u
const LAST_WORD = /(\S+\s?)$/u

export interface PolishOptions {
  /** `T1` -> "CRM" (sources.ts `lookupBadges`). */
  lookups: Map<string, string>
  /** Interfeys tili o'zbek lotin - tutuq belgilarini tekislash. */
  uzLatin: boolean
}

function relabelChips(root: HTMLElement, lookups: Map<string, string>): void {
  for (const chip of root.querySelectorAll<HTMLElement>('.vmd-cite')) {
    if (!chip.dataset.marker) chip.dataset.marker = chip.textContent?.trim() ?? ''
    if (!chip.classList.contains('vmd-cite--tool')) continue
    const label = lookups.get(chip.dataset.marker)
    if (label && chip.textContent !== label) chip.textContent = label
  }
}

/** Uzbek lotin: o'/g' -> oʻ/gʻ (turned comma), boshqa harf'harf -> ʼ (apostrof). */
export function uzApostrophes(text: string): string {
  return text.replace(/([OoGg])['‘’`]/gu, '$1ʻ').replace(/(\p{L})['’`](?=\p{L})/gu, '$1ʼ')
}

function normalizeApostrophes(root: HTMLElement): void {
  const doc = root.ownerDocument
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const value = node.nodeValue ?? ''
    if (!/['‘’`]/.test(value) || node.parentElement?.closest(SKIP)) continue
    const next = uzApostrophes(value)
    if (next !== value) node.nodeValue = next
  }
}

function glueChips(root: HTMLElement): void {
  const doc = root.ownerDocument
  for (const chip of root.querySelectorAll<HTMLElement>('.vmd-cite')) {
    if (chip.parentElement?.classList.contains('tg-glue')) continue
    const parent = chip.parentNode
    if (!parent) continue
    const prev = chip.previousSibling
    const next = chip.nextSibling
    // Ketma-ket chiplar ("[1][2]"): oldingi bo'lakka qo'shiladi.
    const glue =
      prev instanceof HTMLElement && prev.classList.contains('tg-glue')
        ? prev
        : (() => {
            const span = doc.createElement('span')
            span.className = 'tg-glue'
            parent.insertBefore(span, chip)
            if (prev && prev.nodeType === Node.TEXT_NODE) {
              const value = prev.nodeValue ?? ''
              const m = LAST_WORD.exec(value)
              if (m && m[1].trim()) {
                prev.nodeValue = value.slice(0, value.length - m[1].length)
                span.appendChild(doc.createTextNode(m[1]))
              }
            }
            return span
          })()
    glue.appendChild(chip)
    if (next && next.nodeType === Node.TEXT_NODE) {
      const value = next.nodeValue ?? ''
      const m = TRAILING.exec(value)
      if (m) {
        next.nodeValue = value.slice(m[0].length)
        glue.appendChild(doc.createTextNode(m[0]))
      }
    }
  }
}

export function polishAnswer(root: HTMLElement, options: PolishOptions): void {
  relabelChips(root, options.lookups)
  if (options.uzLatin) normalizeApostrophes(root)
  glueChips(root)
}

/** MarkdownMessage'ning `.vmd` ildizini kuzatadi va har yangi chizishdan keyin
 *  pardozlaydi. O'z o'zgarishlarimiz kuzatuvni qayta qo'zg'atmaydi (uzib-ulash). */
export function observeAnswer(root: HTMLElement, options: () => PolishOptions): () => void {
  let observer: MutationObserver | null = null
  const run = () => {
    observer?.disconnect()
    polishAnswer(root, options())
    observer?.takeRecords()
    observer?.observe(root, { childList: true, subtree: true })
  }
  observer = new MutationObserver(run)
  run()
  return () => observer?.disconnect()
}

/** Javobning ODDIY matni ("Matnni belgilash" oynasi uchun): markdown belgilarisiz,
 *  chiplarsiz, ro'yxat va jadval o'qiladigan shaklda. */
export function plainText(root: HTMLElement): string {
  const clone = root.cloneNode(true) as HTMLElement
  clone.querySelectorAll('.vmd-cite, .vmd-caret').forEach((el) => el.remove())
  const out: string[] = []
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push((node.nodeValue ?? '').replace(/\s+/g, ' '))
      return
    }
    if (!(node instanceof HTMLElement)) return
    const tag = node.tagName
    if (tag === 'BR') {
      out.push('\n')
      return
    }
    if (tag === 'LI') out.push('\n• ')
    if (tag === 'TR') out.push('\n')
    if (tag === 'TD' || tag === 'TH') {
      if (node.previousElementSibling) out.push(' — ')
    }
    node.childNodes.forEach(walk)
    if (/^(P|H[1-6]|UL|OL|TABLE|PRE|BLOCKQUOTE)$/.test(tag)) out.push('\n\n')
  }
  walk(clone)
  return (
    out
      .join('')
      // Olib tashlangan chip o'rnida qolgan bo'shliq: "ko'rsatiladi ." -> "ko'rsatiladi."
      .replace(/[ \t]+([.,;:!?)»])/g, '$1')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n[ \t]+/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/^\s+|\s+$/g, '')
  )
}

/** Oqim (yoki "To'xtatish") yopilmagan `**` da qolsa, markdown uni yulduzcha bo'lib
 *  ko'rsatadi ("**15 daqiqadan"). Juft bo'lmasa - oxiriga vaqtincha yopuvchi qo'shiladi:
 *  qalin matn darhol qalin ko'rinadi (kod bloki ichidagilar hisobga olinmaydi). */
export function closeDangling(text: string): string {
  const outside = text.replace(/```[\s\S]*?(```|$)/g, '').replace(/`[^`\n]*`/g, '')
  const pairs = outside.match(/\*\*/g)?.length ?? 0
  return pairs % 2 === 1 ? `${text.replace(/\s+$/, '')}**` : text
}

/** Oqim paytida jadvalning chala qatori (hali `\n` kelmagan) bo'sh kataklar bo'lib
 *  chiqadi - uni kelguncha yashiramiz. Ajratgich (`|---|`) hali kelmagan sarlavha
 *  qatori ham ("| a | b |" oddiy matn bo'lib ko'rinardi). */
export function trimStreamingTable(text: string): string {
  const lines = text.split('\n')
  const last = lines[lines.length - 1]
  if (/^\s*\|/.test(last)) lines.pop()
  else return text
  const lastFull = lines[lines.length - 1] ?? ''
  const before = lines[lines.length - 2] ?? ''
  if (/^\s*\|/.test(lastFull) && !/^\s*\|/.test(before)) lines.pop()
  return lines.join('\n')
}
