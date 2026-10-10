/** v3 javobi (markdown) - telefonda yulduzcha/panjarasiz: sarlavha, ro'yxat, qalin, kursiv, kod. */
import { blocksToText, parseInline, parseMarkdownLite } from '@/lib/markdownLite';

describe('markdownLite', () => {
  it('inline: bold, italic, code; links -> text; citation markers removed', () => {
    expect(parseInline('**Loyiha** topilmadi, *aniqlang* va `DVSIB` ni tekshiring [T1].')).toEqual([
      { text: 'Loyiha', bold: true },
      { text: ' topilmadi, ' },
      { text: 'aniqlang', italic: true },
      { text: ' va ' },
      { text: 'DVSIB', code: true },
      { text: ' ni tekshiring.' },
    ]);
    expect(parseInline('Batafsil: [vazifa](https://crm.example/x) [2]')).toEqual([{ text: 'Batafsil: vazifa' }]);
    // Ko'paytirish va so'z ichidagi yulduzcha kursiv emas.
    expect(parseInline('2*3*4 = 24')).toEqual([{ text: '2*3*4 = 24' }]);
    expect(parseInline('__muhim__')).toEqual([{ text: 'muhim', bold: true }]);
  });

  it('blocks: headings, bullets (nested, numbered), paragraphs, quotes, tables, rules', () => {
    const blocks = parseMarkdownLite(
      [
        '### Natija',
        'Birinchi qator',
        'davomi',
        '',
        '- bir',
        '  - ichki',
        '2. ikki',
        '> iqtibos',
        '---',
        '| Maydon | Qiymat |',
        '|---|---|',
        '| Loyiha | DVSIB |',
        '```',
        'kod',
        '```',
      ].join('\r\n'),
    );
    expect(blocks.map((b) => b.kind)).toEqual(['heading', 'para', 'bullet', 'bullet', 'bullet', 'para', 'para', 'para']);
    expect(blocksToText(blocks)).toBe(
      ['Natija', 'Birinchi qator\ndavomi', '• bir', '  • ichki', '2. ikki', 'iqtibos', 'Maydon · Qiymat\nLoyiha · DVSIB', 'kod'].join('\n'),
    );
  });

  it('empty input -> nothing', () => {
    expect(parseMarkdownLite('')).toEqual([]);
    expect(parseMarkdownLite(null)).toEqual([]);
    expect(parseMarkdownLite('\n\n  \n')).toEqual([]);
  });
});
