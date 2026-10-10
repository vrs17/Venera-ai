/**
 * Javob matni (Markdown) -> native ko'rinish. Tahlil `markdown-it` bilan - Mini App
 * bilan BIR XIL parser (bir xil javob ikki joyda bir xil bo'linadi). HTML o'chiq
 * (`html: false`) - yordamchi matnidagi teglar oddiy matn bo'lib qoladi.
 *
 * Qo'llanadi: sarlavha, paragraf, qalin/kursiv/chizilgan, ichki kod, kod bloki
 * (gorizontal aylanadi), ro'yxatlar (ichma-ich), iqtibos, chiziq, JADVAL (gorizontal
 * aylanadi - HR javoblarida jadval ko'p) va havola (tashqi brauzerda).
 *
 * Texnik belgilar (2026-10-10, egasining skrinshoti - CRM vazifalari javobi; Mini App
 * `answerMarks.ts` bilan bir xil qoida):
 *  - `[T2]` (jonli HRM/CRM so'rovi) matnda YASHIRILADI: har band oxiridagi kulrang "T2"
 *    qutisi javobni o'qishni qiyinlashtirardi; qaysi so'rov ekani "Manbalar" tugmasida qoladi;
 *  - `[1]` (hujjat) - kichik yuqori indeks ("qoldi¹"), bosilsa manbalar ochiladi;
 *  - vazifa kaliti (`DVSIB-245`) - kichik va xira: vazifa nomi asosiy bo'lib qolsin.
 * Kod ichiga (`code`, kod bloki) tegilmaydi.
 *
 * Izohlar (2026-10-10, yordamchi 3.3; web `components/chat/answerNotes.ts` bilan bir qoida):
 *  - "Eslatma: ..." xatboshisi - jim izoh bloki (kichik, xira, chapda chiziq), FAQAT oldida
 *    boshqa mazmun bo'lsa: javob "Eslatma:" bilan BOSHLANSA, u javobning o'zi - oddiy matn;
 *  - oxirgi "Manba: DWH, Biznes 24/7" qatori - kichik xira izoh ("N manba" tugmasini takrorlaydi).
 */
import MarkdownIt from 'markdown-it';
import type Token from 'markdown-it/lib/token.mjs';
import { memo, useMemo, type ReactNode } from 'react';
import { Linking, ScrollView, StyleSheet, Text, View, type TextStyle } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { useTheme, type Theme } from '@/ui/theme';

const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false });

interface Node {
  token: Token;
  children: Node[];
}

/** Tekis token oqimi -> daraxt (`nesting`: +1 ochiladi, -1 yopiladi, 0 - yakka). */
function treeOf(tokens: Token[]): Node[] {
  const root: Node[] = [];
  const stack: Node[][] = [root];
  for (const token of tokens) {
    const level = stack[stack.length - 1];
    if (token.nesting === 1) {
      const node: Node = { token, children: [] };
      level.push(node);
      stack.push(node.children);
    } else if (token.nesting === -1) {
      if (stack.length > 1) stack.pop();
    } else {
      level.push({ token, children: [] });
    }
  }
  return root;
}

/** Platforma so'rovi belgilari: `[T1]`, `[T1, T2]`, `[T1][T2]` - oldidagi bo'shliq bilan
 *  ("kech qoldi [T2]." -> "kech qoldi."). */
const TOOL_MARKS = /[ \u00a0]*\[T\d{1,3}(?:\s*[,;]\s*T?\d{1,3})*\]/g;
/** Hujjat iqtibosi `[1]` - oldidagi bo'shliq ham olinadi: indeks so'zga yopishsin va
 *  qator ko'chganda yolg'iz qolib ketmasin. */
const CITE = /[ \u00a0]*\[(\d{1,3})\]/g;
/**
 * Vazifa kaliti: KATTA harfli loyiha kodi (2-10 belgi) + chiziqcha + raqam (`DVSIB-245`,
 * `HR2-17`). So'z ichida (`xDVSIB-1`, `DVSIB-245a`, `A-B-12`, `oʻDVSIB-3`) - kalit emas. Lotin,
 * o'zbekcha `ʻ`/`ʼ` va kirill aniq oraliq bilan: `\p{L}` va lookbehind'ga tayanmaymiz (Hermes
 * versiyasiga bog'liq).
 */
const TASK_KEY = /(^|[^A-Za-z0-9_\u00C0-\u024F\u02B0-\u02FF\u0400-\u04FF-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![A-Za-z0-9_\u00C0-\u024F\u02B0-\u02FF\u0400-\u04FF]|-\d)/g;
/**
 * Kalitga o'xshagan, lekin vazifa kaliti BO'LMAGAN keng tarqalgan yozuvlar (`COVID-19`, `UTF-8`,
 * `ISO-9001`, `SHA-256`, `Q3-2026`, `H1-2026`): ular xira bo'lsa javobdagi oddiy ma'lumot
 * "texnik izoh"dek ko'rinardi. Web `answerMarks.ts` bilan bir xil ro'yxat.
 */
const NOT_TASK_PREFIX = /^(?:COVID|SARS|UTF|ISO|IEC|SHA|MD|RFC|TLS|SSL|HTTP|MRZ|GMT|UTC|CVE|EN|GOST|[QH][1-4])$/;

export function isTaskKey(key: string): boolean {
  const m = /^([A-Z][A-Z0-9]{1,9})-\d{1,6}$/.exec(key);
  return !!m && !NOT_TASK_PREFIX.test(m[1]);
}
const SUPERSCRIPT = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];

/** `12` -> `¹²` (Unicode yuqori indeks: Android'da ichma-ich <Text> ni yuqoriga ko'tarib bo'lmaydi). */
export function superscript(n: string): string {
  return n.replace(/\d/g, (d) => SUPERSCRIPT[Number(d)]);
}

/*
 * IZOH VA MANBA QATORLARI. Javob tili interfeys tilidan farq qilishi mumkin - HAMMA tildagi
 * so'z taniladi. `u` bayrog'i va lookbehind yo'q: Hermes versiyasiga tayanmaymiz (kirill
 * harflari `i` bilan `u` siz ham katta-kichik farqisiz taniladi).
 */
/** Qator boshidagi eslatma: ixtiyoriy qalin/kursiv (`**Eslatma:**`), ixtiyoriy ℹ️, so'z va ikki nuqta. */
const NOTE_LINE = /^[ \t]{0,3}(?:[*_]{1,2})?(?:\u2139\uFE0F?[ \t]*)?(?:eslatma|эслатма|примечание|note)[ \t]*(?:[*_]{1,2})?[ \t]*:/i;
/** Manba qatori ("Manba:", "Manbalar:", "Манба:", "Источник(и):", "Source(s):") - chekinishsiz. */
const SOURCE_LINE = /^(?:[*_]{1,2})?(?:manba(?:lar)?|манба(?:лар)?|источники?|sources?)[ \t]*(?:[*_]{1,2})?[ \t]*:/i;
/** Chizilgan xatboshining matni (belgilarsiz). */
const NOTE_TEXT = /^\s*(?:\u2139\uFE0F?\s*)?(?:eslatma|эслатма|примечание|note)\s*:/i;
const SOURCE_TEXT = /^\s*(?:manba(?:lar)?|манба(?:лар)?|источники?|sources?)\s*:/i;
const FENCE = /^[ \t]{0,3}(`{3,}|~{3,})/;
const NOTE_WORDS = /(eslatma|эслатма|примечание|note|manba|манба|источник|source)/i;

/**
 * Eslatma yoki manba qatori oldingi qatorga yopishgan bo'lsa (bo'sh qatorsiz) - orasiga bo'sh
 * qator: aks holda Markdown uni oldingi xatboshining davomi qilib yuborardi. Kod bloki ichida emas.
 */
export function separateNotes(markdown: string): string {
  if (!markdown || !NOTE_WORDS.test(markdown)) return markdown;
  const out: string[] = [];
  let fence: string | null = null;
  for (const line of markdown.split('\n')) {
    const f = FENCE.exec(line);
    if (f) {
      if (!fence) fence = f[1][0];
      else if (f[1][0] === fence) fence = null;
    } else if (!fence && (NOTE_LINE.test(line) || SOURCE_LINE.test(line)) && out.length && out[out.length - 1].trim()) {
      out.push('');
    }
    out.push(line);
  }
  return out.join('\n');
}

/** Blok matni (Markdown belgilarisiz) - DOM `textContent` o'rnida. Rasm - "mazmun bor" belgisi. */
function textOf(node: Node): string {
  const { token } = node;
  if (token.type === 'fence' || token.type === 'code_block') return token.content;
  if (token.type === 'inline') {
    return (token.children ?? [])
      .map((c) => (c.type === 'text' || c.type === 'code_inline' ? c.content : c.type === 'image' ? '\uFFFC' : c.type.endsWith('break') ? ' ' : ''))
      .join('');
  }
  return node.children.map(textOf).join('');
}

function hasContent(node: Node): boolean {
  if (node.token.type === 'hr') return false;
  if (node.token.type === 'table_open') return true;
  return !!textOf(node).trim();
}

const isNoteBlock = (node: Node) => node.token.type === 'paragraph_open' && NOTE_TEXT.test(textOf(node));

export type NoteRole = 'note' | 'source' | null;

/**
 * Yuqori darajadagi bloklar roli (web `markNotes` bilan bir xil): faqat yuqori darajadagi
 * xatboshi (ro'yxat, jadval, iqtibos ichidagisi emas - u boshqa narsaning bir qismi).
 *  - eslatma - oldida mazmun bo'lsa `note`; javob u bilan BOSHLANSA - oddiy (va u mazmun);
 *  - manba - oldida mazmun bo'lsa va undan keyin faqat bo'sh blok yoki eslatma kelsa `source`.
 */
function rolesOf(tree: Node[]): NoteRole[] {
  const roles: NoteRole[] = tree.map(() => null);
  let content = false;
  tree.forEach((node, i) => {
    const isP = node.token.type === 'paragraph_open';
    const text = isP ? textOf(node) : '';
    if (isP && NOTE_TEXT.test(text)) {
      if (content) roles[i] = 'note';
      else content = true;
      return;
    }
    if (isP && content && SOURCE_TEXT.test(text) && tree.slice(i + 1).every((b) => !hasContent(b) || isNoteBlock(b))) {
      roles[i] = 'source';
      return;
    }
    if (hasContent(node)) content = true;
  });
  return roles;
}

/** Testlar uchun: Markdown -> yuqori darajadagi bloklar matni va roli. */
export function noteRoles(markdown: string): { text: string; role: NoteRole }[] {
  const tree = treeOf(md.parse(separateNotes(markdown), {}));
  const roles = rolesOf(tree);
  return tree.map((node, i) => ({ text: textOf(node).trim(), role: roles[i] }));
}

export function stripToolMarks(text: string): string {
  return text.replace(TOOL_MARKS, '');
}

export type AnswerPiece = { kind: 'text'; text: string } | { kind: 'cite'; n: string } | { kind: 'key'; text: string };

/**
 * Matn bo'lagi -> oddiy matn, hujjat iqtiboslari va vazifa kalitlari; `[Tn]` tashlab yuboriladi.
 * `cites: false` - `[1]` oddiy matn bo'lib qoladi (havola matni ichida).
 */
export function answerPieces(text: string, { cites = true }: { cites?: boolean } = {}): AnswerPiece[] {
  const out: AnswerPiece[] = [];
  const pushText = (chunk: string) => {
    let last = 0;
    for (const m of chunk.matchAll(TASK_KEY)) {
      if (!isTaskKey(m[2])) continue;
      const start = (m.index ?? 0) + m[1].length;
      if (start > last) out.push({ kind: 'text', text: chunk.slice(last, start) });
      out.push({ kind: 'key', text: m[2] });
      last = start + m[2].length;
    }
    if (last < chunk.length) out.push({ kind: 'text', text: chunk.slice(last) });
  };
  const clean = stripToolMarks(text);
  if (!cites) {
    pushText(clean);
    return out;
  }
  let last = 0;
  for (const m of clean.matchAll(CITE)) {
    const at = m.index ?? 0;
    if (at > last) pushText(clean.slice(last, at));
    out.push({ kind: 'cite', n: m[1] });
    last = at + m[0].length;
  }
  if (last < clean.length) pushText(clean.slice(last));
  return out;
}

export interface AnswerMarkdownProps {
  text: string;
  /** `[n]` bosildi. */
  onCite?: (marker: string) => void;
  /** Oqim davom etmoqda - oxirida miltillovchi kursor. */
  streaming?: boolean;
}

function AnswerMarkdownImpl({ text, onCite, streaming }: AnswerMarkdownProps) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const tree = useMemo(() => treeOf(md.parse(separateNotes(text), {})), [text]);
  const roles = useMemo(() => rolesOf(tree), [tree]);

  /** Inline tokenlar -> ichma-ich <Text>. */
  function inline(tokens: Token[], key: string): ReactNode[] {
    const out: ReactNode[] = [];
    const style: TextStyle[] = [];
    let href: string | null = null;
    tokens.forEach((tk, i) => {
      const k = `${key}-${i}`;
      switch (tk.type) {
        case 'strong_open':
          style.push(s.strong);
          break;
        case 'em_open':
          style.push(s.em);
          break;
        case 's_open':
          style.push(s.strike);
          break;
        case 'strong_close':
        case 'em_close':
        case 's_close':
          style.pop();
          break;
        case 'link_open':
          href = tk.attrGet('href');
          style.push(s.link);
          break;
        case 'link_close':
          href = null;
          style.pop();
          break;
        case 'code_inline':
          // `DVSIB-245` ni yordamchi ko'pincha kod sifatida yozadi - kod qutisi kalitni
          // yanada bo'rttirardi; yolg'iz kalit oddiy xira kalit bo'lib chiqadi.
          out.push(
            <Text key={k} style={[...style, isTaskKey(tk.content.trim()) ? s.taskKey : s.codeInline]}>
              {tk.content}
            </Text>,
          );
          break;
        case 'softbreak':
          out.push(' ');
          break;
        case 'hardbreak':
          out.push('\n');
          break;
        case 'image':
          out.push(tk.content || '');
          break;
        case 'text': {
          const url = href;
          const open = url ? () => void Linking.openURL(url).catch(() => {}) : undefined;
          // Havola ichida `[1]` iqtibos emas (havola matnining o'zi), lekin kalit baribir xira.
          const pieces = answerPieces(tk.content, { cites: !url });
          let prevCite = false;
          pieces.forEach((piece, j) => {
            const pk = `${k}-${j}`;
            if (piece.kind === 'cite') {
              out.push(
                <Text
                  key={pk}
                  style={[s.cite, onCite ? s.citeLink : null]}
                  onPress={onCite ? () => onCite(piece.n) : undefined}
                  accessibilityRole={onCite ? 'button' : undefined}
                  accessibilityLabel={t('chat.citeN', { n: piece.n })}>
                  {/* Ketma-ket iqtiboslar "¹²" (o'n ikki) bo'lib qolmasin - vergul bilan, web
                      chat va Mini App'dagi kabi ("¹,²"). */}
                  {`${prevCite ? ',' : ''}${superscript(piece.n)}`}
                </Text>,
              );
              prevCite = true;
              return;
            }
            prevCite = false;
            if (!piece.text) return;
            if (piece.kind === 'key') {
              out.push(
                <Text key={pk} style={[...style, s.taskKey]} onPress={open}>
                  {piece.text}
                </Text>,
              );
              return;
            }
            out.push(
              <Text key={pk} style={style.length ? [...style] : undefined} onPress={open}>
                {piece.text}
              </Text>,
            );
          });
          break;
        }
        default:
          if (tk.content) out.push(tk.content);
      }
    });
    return out;
  }

  /** `top` - yuqori daraja: faqat u yerda eslatma/manba roli bor (`rolesOf`). */
  function block(nodes: Node[], key: string, tight = false, depth = 0, top = false): ReactNode[] {
    return nodes.map((node, i) => {
      const { token } = node;
      const k = `${key}.${i}`;
      switch (token.type) {
        case 'paragraph_open': {
          const content = node.children.flatMap((c) => (c.token.type === 'inline' ? inline(c.token.children ?? [], k) : []));
          const role = top ? roles[i] : null;
          if (role === 'note') {
            return (
              <View key={k} testID="answer-note" style={s.note}>
                <Text style={s.noteText}>{content}</Text>
              </View>
            );
          }
          if (role === 'source') {
            return (
              <Text key={k} testID="answer-source" style={s.sourceLine}>
                {content}
              </Text>
            );
          }
          return (
            <Text key={k} style={[s.p, tight || token.hidden ? s.pTight : null]}>
              {content}
            </Text>
          );
        }
        case 'heading_open': {
          const level = Number(token.tag.slice(1)) || 3;
          const content = node.children.flatMap((c) => (c.token.type === 'inline' ? inline(c.token.children ?? [], k) : []));
          return (
            <Text key={k} style={[s.h, level <= 1 ? s.h1 : level === 2 ? s.h2 : s.h3]} accessibilityRole="header">
              {content}
            </Text>
          );
        }
        case 'bullet_list_open':
        case 'ordered_list_open': {
          const ordered = token.type === 'ordered_list_open';
          const start = Number(token.attrGet('start') ?? 1) || 1;
          const items = node.children.filter((c) => c.token.type === 'list_item_open');
          return (
            <View key={k} style={[s.list, depth > 0 ? s.listNested : null]}>
              {items.map((item, j) => (
                <View key={`${k}-${j}`} style={s.li}>
                  <Text style={[s.bullet, ordered ? s.number : null]}>{ordered ? `${start + j}.` : depth % 2 ? '◦' : '•'}</Text>
                  <View style={s.liBody}>{block(item.children, `${k}-${j}`, true, depth + 1)}</View>
                </View>
              ))}
            </View>
          );
        }
        case 'blockquote_open':
          return (
            <View key={k} style={s.quote}>
              {block(node.children, k, false, depth)}
            </View>
          );
        case 'fence':
        case 'code_block':
          return (
            <ScrollView key={k} horizontal style={s.codeBlock} contentContainerStyle={s.codeBlockInner} showsHorizontalScrollIndicator={false}>
              <Text style={s.codeText} selectable>
                {token.content.replace(/\n$/, '')}
              </Text>
            </ScrollView>
          );
        case 'hr':
          return <View key={k} style={s.hr} />;
        case 'table_open':
          return <Table key={k} node={node} keyPrefix={k} />;
        case 'inline':
          return <Text key={k} style={s.p}>{inline(token.children ?? [], k)}</Text>;
        default:
          return node.children.length ? <View key={k}>{block(node.children, k, tight, depth)}</View> : null;
      }
    });
  }

  function Table({ node, keyPrefix }: { node: Node; keyPrefix: string }) {
    const rows: { head: boolean; cells: { node: Node; align: string | null }[] }[] = [];
    for (const section of node.children) {
      const head = section.token.type === 'thead_open';
      for (const tr of section.children) {
        if (tr.token.type !== 'tr_open') continue;
        rows.push({
          head,
          cells: tr.children
            .filter((c) => c.token.type === 'th_open' || c.token.type === 'td_open')
            .map((c) => ({ node: c, align: (c.token.attrGet('style') ?? '').includes('right') ? 'right' : null })),
        });
      }
    }
    return (
      <ScrollView horizontal style={s.tableWrap} showsHorizontalScrollIndicator={false}>
        <View style={s.table}>
          {rows.map((row, r) => (
            <View key={`${keyPrefix}-r${r}`} style={[s.tr, row.head ? s.trHead : null, r === rows.length - 1 ? s.trLast : null]}>
              {row.cells.map((cell, c) => (
                <View key={`${keyPrefix}-r${r}c${c}`} style={s.td}>
                  <Text style={[s.tdText, row.head ? s.thText : null, cell.align === 'right' ? s.right : null]}>
                    {cell.node.children.flatMap((x) => (x.token.type === 'inline' ? inline(x.token.children ?? [], `${keyPrefix}-${r}-${c}`) : []))}
                  </Text>
                </View>
              ))}
            </View>
          ))}
        </View>
      </ScrollView>
    );
  }

  return (
    <View>
      {block(tree, 'm', false, 0, true)}
      {streaming ? <View style={s.caret} /> : null}
    </View>
  );
}

export const AnswerMarkdown = memo(AnswerMarkdownImpl);

function makeStyles(th: Theme) {
  return StyleSheet.create({
    p: { color: th.text, fontSize: 16, lineHeight: 25, marginBottom: 10 },
    pTight: { marginBottom: 4 },
    strong: { fontWeight: '700' },
    em: { fontStyle: 'italic' },
    strike: { textDecorationLine: 'line-through' },
    link: { color: th.brand, textDecorationLine: 'underline' },
    codeInline: {
      fontFamily: 'monospace',
      fontSize: 14,
      backgroundColor: th.surfaceAlt,
      color: th.text,
    },
    // Hujjat iqtibosi: qutisiz yuqori indeks - matn asosiy, raqam faqat "manba bor" ishorasi.
    cite: { fontWeight: '700', color: th.textMuted },
    citeLink: { color: th.brand },
    // Vazifa kaliti: kichik va xira, qalin matn ichida ham oddiy - vazifa NOMI ko'zga tashlansin.
    taskKey: { fontSize: 13, fontWeight: '400', fontStyle: 'normal', color: th.textMuted },
    h: { color: th.text, fontWeight: '700', marginTop: 6, marginBottom: 8 },
    h1: { fontSize: 22, lineHeight: 29 },
    h2: { fontSize: 19, lineHeight: 26 },
    h3: { fontSize: 17, lineHeight: 24 },
    list: { marginBottom: 8 },
    listNested: { marginTop: 2, marginBottom: 2 },
    li: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 2 },
    bullet: { width: 18, color: th.textSoft, fontSize: 16, lineHeight: 25 },
    number: { width: 24, fontVariant: ['tabular-nums'] },
    liBody: { flex: 1, minWidth: 0 },
    quote: { borderLeftWidth: 3, borderLeftColor: th.borderStrong, paddingLeft: 12, marginBottom: 10 },
    codeBlock: { backgroundColor: th.surfaceAlt, borderRadius: 12, marginBottom: 10 },
    codeBlockInner: { padding: 12 },
    codeText: { fontFamily: 'monospace', fontSize: 13, lineHeight: 19, color: th.text },
    hr: { height: StyleSheet.hairlineWidth, backgroundColor: th.borderStrong, marginVertical: 12 },
    tableWrap: { marginBottom: 12 },
    table: { borderWidth: StyleSheet.hairlineWidth, borderColor: th.borderStrong, borderRadius: 10, overflow: 'hidden' },
    tr: { flexDirection: 'row', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: th.border },
    trHead: { backgroundColor: th.surfaceAlt },
    trLast: { borderBottomWidth: 0 },
    td: { minWidth: 96, maxWidth: 240, paddingHorizontal: 10, paddingVertical: 8 },
    tdText: { color: th.text, fontSize: 14, lineHeight: 20 },
    thText: { fontWeight: '700' },
    right: { textAlign: 'right' },
    caret: { width: 8, height: 16, borderRadius: 2, backgroundColor: th.textMuted, marginTop: -4, opacity: 0.6 },
    // "Eslatma:" - jim izoh: kichik, xira, chapda ingichka chiziq; javob bilan "bahslashmaydi".
    note: {
      marginTop: 6,
      marginBottom: 10,
      paddingVertical: 8,
      paddingHorizontal: 12,
      borderLeftWidth: 3,
      borderLeftColor: th.borderStrong,
      borderTopRightRadius: 8,
      borderBottomRightRadius: 8,
      backgroundColor: th.surfaceAlt,
    },
    noteText: { color: th.textSoft, fontSize: 14, lineHeight: 20 },
    // "Manba: ..." - "N manba" tugmasini takrorlaydi: qutisiz kichik izoh.
    sourceLine: { color: th.textMuted, fontSize: 13, lineHeight: 18, marginTop: 2, marginBottom: 6 },
  });
}
