/**
 * Javob izohlari (yordamchi 3.3; web `components/chat/answerNotes.ts` bilan bir qoida):
 *  - "Eslatma:" (Эслатма / Примечание / Note) xatboshisi oldida mazmun bo'lsa - jim izoh bloki;
 *    javob u bilan BOSHLANSA - javobning o'zi (oddiy matn): "Eslatma: ertaga 10:00 da yig'ilish";
 *  - oxirgi "Manba:" (Манба / Источник / Source) qatori - kichik izoh; undan keyin faqat
 *    eslatma bo'lishi mumkin; oldida mazmun bo'lmasa yoki keyin matn davom etsa - oddiy;
 *  - oldingi qatorga yopishgan eslatma/manba alohida xatboshi bo'ladi (kod bloki ichida emas);
 *  - ro'yxat yoki iqtibos ichidagisi - belgilanmaydi (u boshqa narsaning bir qismi).
 */
import { render, screen, within } from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import { AnswerMarkdown, noteRoles, separateNotes } from '@/features/chat/ui/AnswerMarkdown';
import { useSettings } from '@/features/settings/settingsStore';
import { lightTheme } from '@/ui/theme';

const flat = (el: { props: { style?: unknown } }) => (StyleSheet.flatten(el.props.style as never) ?? {}) as Record<string, unknown>;
const roles = (md: string) => noteRoles(md).map((b) => b.role);

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
});

describe('Eslatma callout (pure rules)', () => {
  it('a note AFTER other content becomes a callout', () => {
    expect(roles("Bugun 3 kishi kechikdi.\n\nEslatma: bugun dam olish kuni, ma'lumot juma kungi.")).toEqual([null, 'note']);
  });

  it('a LEADING note is the answer itself and stays normal (Uzbek "Eslatma" also means a reminder)', () => {
    expect(roles("Eslatma: ertaga 10:00 da yig'ilish")).toEqual([null]);
    expect(roles("Eslatma: ertaga 10:00 da yig'ilish.\n\nXonasi: 3-qavat.")).toEqual([null, null]);
    // Ikkinchi eslatma - birinchisidan keyin, endi izoh.
    expect(roles('Eslatma: ertaga yig\'ilish.\n\nEslatma: xona o\'zgargan.')).toEqual([null, 'note']);
  });

  it('every language, bold / emoji forms', () => {
    for (const note of ['**Eslatma:** sana', '**Eslatma**: sana', 'ℹ️ Eslatma: sana', 'Эслатма: сана', 'Примечание: дата', 'Note: date', 'NOTE: date', '_Note:_ date']) {
      expect([note, roles(`Javob.\n\n${note}`)]).toEqual([note, [null, 'note']]);
    }
    // Faqat so'z boshida va ikki nuqta bilan: "Notebook:" yoki "Eslatmalar ro'yxati" - izoh emas.
    expect(roles('Javob.\n\nNotebook: 5 ta')).toEqual([null, null]);
    expect(roles("Javob.\n\nEslatmalar ro'yxati tayyor")).toEqual([null, null]);
  });

  it('a note glued to the previous line is split into its own paragraph (not inside a code block)', () => {
    expect(separateNotes('Javob matni.\nEslatma: sana boshqa.')).toBe('Javob matni.\n\nEslatma: sana boshqa.');
    expect(roles('Javob matni.\nEslatma: sana boshqa.')).toEqual([null, 'note']);
    const fenced = '```\nkod\nEslatma: kod ichida\n```';
    expect(separateNotes(fenced)).toBe(fenced);
    expect(roles(fenced)).toEqual([null]);
    // So'z yo'q - matn tegilmaydi.
    expect(separateNotes('Oddiy\nmatn')).toBe('Oddiy\nmatn');
  });

  it('only top-level paragraphs: a note inside a list or a quote is part of that block', () => {
    expect(roles('Vazifalar:\n\n- Hisobot\n\n  Eslatma: ertaga')).toEqual([null, null]);
    expect(roles('Javob.\n\n> Eslatma: iqtibos ichida')).toEqual([null, null]);
    expect(noteRoles('Javob.\n\n- Eslatma: band')[1]).toEqual({ text: 'Eslatma: band', role: null });
  });
});

describe('Manba caption (pure rules)', () => {
  it('a trailing "Manba:" line after content becomes a small caption (also when glued)', () => {
    expect(roles('DWH: 12 filial reja bajardi.\n\nManba: DWH, Biznes 24/7')).toEqual([null, 'source']);
    expect(roles('DWH: 12 filial reja bajardi.\nManba: DWH')).toEqual([null, 'source']);
    for (const line of ['Manbalar: DWH', '**Manba:** DWH', 'Манба: DWH', 'Источник: DWH', 'Источники: DWH', 'Source: DWH', 'Sources: DWH']) {
      expect([line, roles(`Javob.\n\n${line}`)]).toEqual([line, [null, 'source']]);
    }
  });

  it('may be followed only by a note; otherwise (more text, or nothing before it) it stays normal', () => {
    expect(roles('Javob.\n\nManba: DWH\n\nEslatma: juma kungi')).toEqual([null, 'source', 'note']);
    expect(roles('Javob.\n\nManba: DWH\n\nYana matn.')).toEqual([null, null, null]);
    expect(roles('Manba: DWH')).toEqual([null]);
    expect(roles('Javob.\n\nManba: DWH\n\n---')).toEqual([null, 'source', null]);
  });
});

describe('AnswerMarkdown rendering', () => {
  it('renders the note as a muted callout with a left rule and the source line as a small caption', async () => {
    await render(<AnswerMarkdown text={"Bugun 3 kishi kechikdi.\n\nManba: HRM\n\n**Eslatma:** bugun shanba, ma'lumot juma kungi."} />);
    const note = screen.getByTestId('answer-note');
    expect(flat(note)).toMatchObject({ borderLeftWidth: 3, borderLeftColor: lightTheme.borderStrong, backgroundColor: lightTheme.surfaceAlt });
    // Izoh matni kichik va xira; qalin "Eslatma:" ham shu rangda (javob bilan bahslashmaydi).
    expect(flat(note.children[0] as never)).toMatchObject({ fontSize: 14, color: lightTheme.textSoft });
    expect(within(note).getByText('Eslatma:')).toBeTruthy();
    const source = screen.getByTestId('answer-source');
    expect(flat(source)).toMatchObject({ fontSize: 13, color: lightTheme.textMuted });
    expect(screen.getByText('Manba: HRM')).toBeTruthy();
    // Asosiy javob - izoh ichida emas.
    expect(within(note).queryByText('Bugun 3 kishi kechikdi.')).toBeNull();
    expect(screen.getByText('Bugun 3 kishi kechikdi.')).toBeTruthy();
  });

  it('a leading "Eslatma:" answer is rendered as a normal paragraph (no callout, no caption)', async () => {
    await render(<AnswerMarkdown text={"Eslatma: ertaga 10:00 da yig'ilish"} />);
    expect(screen.queryByTestId('answer-note')).toBeNull();
    expect(screen.queryByTestId('answer-source')).toBeNull();
    expect(screen.getByText("Eslatma: ertaga 10:00 da yig'ilish")).toBeTruthy();
  });
});
