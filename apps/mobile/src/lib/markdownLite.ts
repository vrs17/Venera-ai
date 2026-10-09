/**
 * AI javobi uchun "yengil markdown": sarlavha, ro'yxat, paragraf va qalin/kursiv/kod.
 *
 * NIMA UCHUN o'zimizniki: v3 javobi markdown (`**qalin**`, `- band`, `### Sarlavha`) -
 * xom ko'rsatilsa telefonda yulduzcha va panjaralar chiqadi. To'liq markdown kutubxonasi
 * (va WebView) bu ikki-uch qoida uchun ortiqcha. HTML hech qachon chizilmaydi - faqat
 * matn bo'laklari, ya'ni javobdagi hech narsa "kod" bo'lib ishlamaydi.
 *
 * Havola `[matn](url)` -> matn (javobdagi havolani bosish shart emas); manba belgilari
 * `[T1]`, `[2]`, `[^3]` olib tashlanadi - chatdagi manba chiplari bu yerda yo'q.
 */

export interface Inline {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
}

export type Block =
  | { kind: 'heading'; inlines: Inline[] }
  | { kind: 'para'; inlines: Inline[] }
  | { kind: 'bullet'; marker: string; depth: number; inlines: Inline[] };

const CITATION = /\s?\[(?:T\d{1,3}|\^?\d{1,3})\]/g;
const LINK = /\[([^\]\n]+)\]\((?:[^)\s]+)\)/g;

/** Satr ichidagi belgilar: `code`, **qalin** / __qalin__, *kursiv*. */
export function parseInline(src: string): Inline[] {
  const text = src.replace(LINK, '$1').replace(CITATION, '');
  const out: Inline[] = [];
  // Kursiv: oldingi belgi guruhda (lookbehind'siz - har qanday JS dvigatelida ishlaydi),
  // `2*3*4` yoki `snake*case` kursiv bo'lib qolmasin.
  const re = /`([^`\n]+)`|\*\*([^*\n]+?)\*\*|__([^_\n]+?)__|(^|[^\w*])\*([^*\s][^*\n]*?)\*(?![\w*])/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    const before = text.slice(last, m.index) + (m[5] != null ? (m[4] ?? '') : '');
    if (before) out.push({ text: before });
    if (m[1] != null) out.push({ text: m[1], code: true });
    else if (m[2] != null || m[3] != null) out.push({ text: (m[2] ?? m[3]) as string, bold: true });
    else out.push({ text: m[5], italic: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  // Qo'shni oddiy bo'laklar birlashtiriladi (bitta Text - o'qish va qidirish oson).
  const merged: Inline[] = [];
  for (const part of out) {
    const prev = merged[merged.length - 1];
    if (prev && !prev.bold && !prev.italic && !prev.code && !part.bold && !part.italic && !part.code) prev.text += part.text;
    else merged.push({ ...part });
  }
  return merged.filter((p) => p.text !== '');
}

/** Jadval qatori `| a | b |` -> "a · b"; ajratuvchi `|---|` qatori - bo'sh. */
function tableRow(line: string): string | null {
  const t = line.trim();
  if (!t.startsWith('|') || !t.endsWith('|')) return null;
  const cells = t.slice(1, -1).split('|').map((c) => c.trim());
  if (cells.every((c) => /^:?-{2,}:?$/.test(c))) return '';
  return cells.filter(Boolean).join(' · ');
}

export function parseMarkdownLite(src: string | null | undefined): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    const joined = para.join('\n').trim();
    if (joined) blocks.push({ kind: 'para', inlines: parseInline(joined) });
    para = [];
  };
  for (const raw of (src ?? '').replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim() || /^\s*```/.test(line) || /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flush();
      continue;
    }
    const heading = /^\s{0,3}#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: 'heading', inlines: parseInline(heading[1].replace(/\s#+\s*$/, '')) });
      continue;
    }
    const bullet = /^(\s*)(?:[-*+•]|(\d{1,3})[.)])\s+(.*)$/.exec(line);
    if (bullet) {
      flush();
      const depth = Math.min(3, Math.floor(bullet[1].replace(/\t/g, '  ').length / 2));
      blocks.push({ kind: 'bullet', marker: bullet[2] ? `${bullet[2]}.` : '•', depth, inlines: parseInline(bullet[3]) });
      continue;
    }
    const row = tableRow(line);
    if (row !== null) {
      if (row) para.push(row);
      continue;
    }
    para.push(line.replace(/^\s*>\s?/, ''));
  }
  flush();
  return blocks;
}

/** Bloklar -> oddiy matn (nusxalash, test). */
export function blocksToText(blocks: Block[]): string {
  return blocks
    .map((b) => {
      const text = b.inlines.map((i) => i.text).join('');
      return b.kind === 'bullet' ? `${'  '.repeat(b.depth)}${b.marker} ${text}` : text;
    })
    .join('\n');
}
