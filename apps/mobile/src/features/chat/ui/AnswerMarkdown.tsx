/**
 * Javob matni (Markdown) -> native ko'rinish. Tahlil `markdown-it` bilan - Mini App
 * bilan BIR XIL parser (bir xil javob ikki joyda bir xil bo'linadi). HTML o'chiq
 * (`html: false`) - yordamchi matnidagi teglar oddiy matn bo'lib qoladi.
 *
 * Qo'llanadi: sarlavha, paragraf, qalin/kursiv/chizilgan, ichki kod, kod bloki
 * (gorizontal aylanadi), ro'yxatlar (ichma-ich), iqtibos, chiziq, JADVAL (gorizontal
 * aylanadi - HR javoblarida jadval ko'p) va havola (tashqi brauzerda).
 * `[1]`, `[T2]` - manba belgilari: kichik "tabletka", bosilsa manba ochiladi.
 */
import MarkdownIt from 'markdown-it';
import type Token from 'markdown-it/lib/token.mjs';
import { memo, useMemo, type ReactNode } from 'react';
import { Linking, ScrollView, StyleSheet, Text, View, type TextStyle } from 'react-native';

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

const CITE = /\[(T?\d{1,3})\]/g;

export interface AnswerMarkdownProps {
  text: string;
  /** `[n]` bosildi. */
  onCite?: (marker: string) => void;
  /** Oqim davom etmoqda - oxirida miltillovchi kursor. */
  streaming?: boolean;
}

function AnswerMarkdownImpl({ text, onCite, streaming }: AnswerMarkdownProps) {
  const th = useTheme();
  const s = useMemo(() => makeStyles(th), [th]);
  const tree = useMemo(() => treeOf(md.parse(text, {})), [text]);

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
          out.push(
            <Text key={k} style={[...style, s.codeInline]}>
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
          const parts = url ? [tk.content] : tk.content.split(CITE);
          parts.forEach((part, j) => {
            if (!part) return;
            // split() bilan ajratilgan guruhlar toq indekslarda - manba belgilari.
            if (!url && j % 2 === 1) {
              out.push(
                <Text
                  key={`${k}-${j}`}
                  style={s.cite}
                  onPress={onCite ? () => onCite(part) : undefined}
                  accessibilityRole={onCite ? 'button' : undefined}>
                  {` ${part} `}
                </Text>,
              );
              return;
            }
            out.push(
              <Text
                key={`${k}-${j}`}
                style={style.length ? [...style] : undefined}
                onPress={url ? () => void Linking.openURL(url).catch(() => {}) : undefined}>
                {part}
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

  function block(nodes: Node[], key: string, tight = false, depth = 0): ReactNode[] {
    return nodes.map((node, i) => {
      const { token } = node;
      const k = `${key}.${i}`;
      switch (token.type) {
        case 'paragraph_open': {
          const content = node.children.flatMap((c) => (c.token.type === 'inline' ? inline(c.token.children ?? [], k) : []));
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
      {block(tree, 'm')}
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
    cite: {
      fontSize: 11,
      lineHeight: 16,
      fontWeight: '700',
      color: th.textSoft,
      backgroundColor: th.surfaceAlt,
    },
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
  });
}
