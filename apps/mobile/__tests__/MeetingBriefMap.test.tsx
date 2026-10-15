/**
 * Yozuv sahifasidagi "Qisqa xulosa" kartasi (bir bosishda nusxa/ulashish), Xulosa
 * tabidagi "Xarita" ko'rinishi (yig'iq ochiladi, shox bosilsa ochiladi, band bosilsa
 * pleer o'sha joyga o'tadi, ro'yxat, kattalik) va sarlavhadagi eksport tugmasi
 * (ko'rib turilgan xulosa bilan). Tarmoqqa chiqmaydi.
 *
 * Eksport varag'i (`ExportSheet`) boshqa bo'limniki - bu yerda faqat unga to'g'ri
 * props berilgani tekshiriladi, shuning uchun soxtasi bilan.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import * as Clipboard from 'expo-clipboard';
import * as ExpoAudio from 'expo-audio';
import { Stack } from 'expo-router';
import { renderRouter } from 'expo-router/testing-library';
import type { ReactNode } from 'react';
import { Share, Text } from 'react-native';

import MeetingRoute from '@/app/meeting/[id]';
import { briefToText, buildBrief } from '@/features/meeting/brief';
import { buildMindMap } from '@/features/meeting/mindmapModel';
import { MindMapView } from '@/features/meeting/MindMapView';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { actionItem, meeting, summary, summaryCard } from './fixtures/server';

jest.mock(
  '@/features/meeting/ExportSheet',
  () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const React = require('react');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { Pressable, Text: RNText } = require('react-native');
    return {
      ExportSheet: (p: { visible: boolean; onClose: () => void; meetingId: string; title: string; hasSummary: boolean; summaryId?: string | null }) =>
        p.visible
          ? React.createElement(
              Pressable,
              { testID: 'export-sheet', onPress: p.onClose },
              React.createElement(RNText, null, `${p.meetingId}|${p.title}|${String(p.hasSummary)}|${p.summaryId ?? '-'}`),
            )
          : null,
    };
  },
  { virtual: true },
);

const ID = 'a'.repeat(32);
// Asosiy xulosada xarita vazifalari jonli ro'yxatdan - tugun id'si vazifa id'si bilan.
const AI = actionItem.id;
const player = (ExpoAudio as unknown as { __player: Record<string, jest.Mock> }).__player;

async function open(api = fakeMeetingsApi(), opts: { withHeader?: boolean } = {}) {
  const services = fakeServices({ meetings: api });
  const wrapper = ({ children }: { children: ReactNode }) => <Providers services={services}>{children}</Providers>;
  const routes: Record<string, () => ReactNode> = { 'meeting/[id]': MeetingRoute };
  if (opts.withHeader) {
    routes._layout = () => <Stack />;
    routes.meetings = () => <Text>meetings-screen</Text>;
  }
  await renderRouter(routes, { initialUrl: `/meeting/${ID}`, wrapper });
  await waitFor(() => expect(screen.getByTestId('meeting-title')).toBeTruthy());
  return { api, services };
}

beforeEach(() => {
  useSettings.setState({ uiLang: 'uz' });
});

describe('short summary card', () => {
  it('sits at the top of the Summary tab in the approved layout', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('brief-card')).toBeTruthy());
    const card = within(screen.getByTestId('brief-card'));
    expect(card.getByText('Qisqa xulosa')).toBeTruthy();
    expect(screen.getByTestId('brief-title')).toHaveTextContent('Narxlar va hisobot');
    expect(screen.getByTestId('brief-meta')).toHaveTextContent('9-oktabr 2026 (juma), 11:00 · 1 soat · 2 ishtirokchi');
    expect(screen.getByTestId('brief-purpose')).toHaveTextContent('Maqsad: Narxlarni kelishish.');
    // Qisqacha - bitta gap (to'liq umumiy xulosa "Batafsil" da yig'iq qatorda).
    expect(screen.getByTestId('brief-overview')).toHaveTextContent("Qisqacha: Aziz narxlarni ko'rib chiqdi.");
    expect(within(screen.getByTestId('brief-keyPoints')).getByText('Asosiy fikr:')).toBeTruthy();
    // Asosiy xulosa - vazifalar jonli ro'yxatdan (Vazifalar tabidagi bitta vazifa).
    await waitFor(() => expect(within(screen.getByTestId('brief-actionItems')).getByText('Vazifa:')).toBeTruthy());
    expect(within(screen.getByTestId('brief-actionItems')).getByText("Hisobotni yuborish. Mas'ul: 2-ishtirokchi. Muddat: 10-oktabr.")).toBeTruthy();
    expect(within(screen.getByTestId('brief-decisions')).getByText('Chegirma berilmaydi (taxminiy, aniqlashtirish kerak).')).toBeTruthy();
    expect(within(screen.getByTestId('brief-openQuestions')).getByText('Ochiq savol:')).toBeTruthy();
    // Karta to'liq bo'limlardan OLDIN.
    const json = JSON.stringify(screen.toJSON());
    expect(json.indexOf('"brief-card"')).toBeLessThan(json.indexOf('"section-overview"'));
    expect(screen.getByText('Batafsil')).toBeTruthy();
  });

  it('copies and shares exactly the card text as plain text (one tap each)', async () => {
    const share = jest.spyOn(Share, 'share').mockResolvedValue({ action: 'sharedAction' });
    await open();
    await waitFor(() => expect(screen.getByTestId('brief-copy')).toBeTruthy());
    const expected = briefToText(buildBrief(summary().content, meeting(), meeting().speakers, { actions: [actionItem] })!);
    await waitFor(() => expect(within(screen.getByTestId('brief-actionItems')).getByText('Vazifa:')).toBeTruthy());
    expect(expected.startsWith('Narxlar va hisobot\n9-oktabr 2026 (juma), 11:00 · 1 soat · 2 ishtirokchi\n\nMaqsad: Narxlarni kelishish.')).toBe(true);
    await fireEvent.press(screen.getByTestId('brief-copy'));
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith(expected);
    await waitFor(() => expect(screen.getByTestId('brief-copy')).toHaveTextContent('Nusxalandi'));
    await fireEvent.press(screen.getByTestId('brief-share'));
    await waitFor(() => expect(share).toHaveBeenCalledWith({ message: expected, title: 'Narxlar va hisobot' }));
    expect(expected).not.toContain('**');
    share.mockRestore();
  });

  it('card chrome follows the app language; the shareable block stays in the summary language (like the file)', async () => {
    useSettings.setState({ uiLang: 'ru' });
    await open();
    await waitFor(() => expect(screen.getByTestId('brief-card')).toBeTruthy());
    expect(screen.getByText('Краткий итог')).toBeTruthy();
    expect(screen.getByTestId('brief-copy')).toHaveTextContent('Копировать');
    expect(screen.getByTestId('brief-share')).toHaveTextContent('Поделиться');
    // "Цель: Narxlarni..." aralashmasi yo'q: blok to'liq xulosa tilida (o'zbekcha).
    expect(screen.getByTestId('brief-meta')).toHaveTextContent('9-oktabr 2026 (juma), 11:00 · 1 soat · 2 ishtirokchi');
    expect(screen.getByTestId('brief-purpose')).toHaveTextContent('Maqsad: Narxlarni kelishish.');
  });

  it('a brief item with evidence seeks the player (the repeated sections below are hidden)', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('brief-openQuestions-0')).toBeTruthy());
    expect(screen.getByTestId('brief-openQuestions-0').props.accessibilityLabel).toBe('Yetkazib berish qachon?, 00:15 dan eshitish');
    await fireEvent.press(screen.getByTestId('brief-openQuestions-0'));
    await waitFor(() => expect(player.seekTo).toHaveBeenCalledWith(15.2));
    // Blok to'liq takrorlaydigan "Ochiq savollar" bo'limi "Batafsil" ostida yo'q.
    expect(screen.queryByTestId('section-openQuestions')).toBeNull();
  });

  it('decision and task rows open their details; tasks keep the CRM button; point/question rows play', async () => {
    await open();
    await waitFor(() => expect(within(screen.getByTestId('brief-actionItems')).getByText('Vazifa:')).toBeTruthy());
    // Qaror: o'q belgisi, bosilsa sabab, kim taklif qildi, iqtibos va ▶ vaqt.
    const d1 = screen.getByTestId('brief-decisions-0');
    expect(d1.props.accessibilityLabel).toBe("Narx 15 mln so'm.: ochish");
    expect(d1.props.accessibilityState).toMatchObject({ expanded: false });
    expect(screen.queryByTestId('brief-decisions-0-details')).toBeNull();
    await fireEvent.press(d1);
    const details = within(screen.getByTestId('brief-decisions-0-details'));
    expect(details.getByText('Sabab: Bozor narxi')).toBeTruthy();
    expect(details.getByText('Taklif: Aziz')).toBeTruthy();
    expect(details.getByText('“kelishdik”')).toBeTruthy();
    expect(details.getByText('Yakuniy')).toBeTruthy();
    await fireEvent.press(details.getByTestId('ev-15.2'));
    await waitFor(() => expect(player.seekTo).toHaveBeenCalledWith(15.2));
    expect(screen.getByTestId('brief-decisions-0').props.accessibilityState).toMatchObject({ expanded: true });
    await fireEvent.press(screen.getByTestId('brief-decisions-0'));
    expect(screen.queryByTestId('brief-decisions-0-details')).toBeNull();
    // Vazifa: mas'ul/muddat kartadagi matnda (jonli), ochilganda - qolgan tafsilot (eskirgan mas'ul emas).
    await fireEvent.press(screen.getByTestId('brief-actionItems-0'));
    const task = within(screen.getByTestId('brief-actionItems-0-details'));
    expect(task.getByText('Natija: PDF hisobot')).toBeTruthy();
    expect(task.queryByText("Mas'ul: 2-ishtirokchi")).toBeNull();
    expect(task.getByText('Muhim')).toBeTruthy();
    // CRM tugmasi kartadagi jonli vazifa ostida (Vazifalar tabidagi o'sha `CrmPanel`).
    expect(screen.getByTestId(`crm-add-${AI}`)).toBeTruthy();
    // Fikr bandi ochilmaydi - bosilsa yozuv o'sha joydan.
    expect(screen.getByTestId('brief-keyPoints-0').props.accessibilityLabel).toBe('Narx kelishildi., 00:15 dan eshitish');
  });

  it('merged facts (alsoIn) and follow-up reasons show as chips on the card rows and in the groups', async () => {
    const s = summary();
    const c = s.content!;
    c.keyPoints[0].alsoIn = [
      { section: 'template', key: 'shortlist', label: 'Tanlangan' },
      { section: 'template', key: 'pros', label: 'Afzallik' },
    ];
    c.decisions[1].alsoIn = [{ section: 'risks', label: 'Xavf' }];
    c.actionItems[0].alsoIn = [{ section: 'nextSteps', label: 'Keyingi qadam' }];
    c.risks[0].mitigation = null;
    c.followUps = [{ id: 'F1', kind: 'risk', ref: 'R1', text: 'Kurs oshishi', reasons: ['no_mitigation'], sourceSegmentIds: [2], start: 4.3 }];
    c.view = { compact: 1, merged: 4 };
    await open(fakeMeetingsApi({ summary: jest.fn(async () => s) }));
    await waitFor(() => expect(screen.getByTestId('brief-keyPoints-0-tags')).toBeTruthy());
    expect(screen.getByTestId('brief-keyPoints-0-tags')).toHaveTextContent('TanlanganAfzallik');
    expect(screen.getByTestId('brief-decisions-1-tags')).toHaveTextContent('Xavf');
    // Jonli vazifa chipi xulosadagi bandidan (`summaryItemId`).
    await waitFor(() => expect(screen.getByTestId('brief-actionItems-0-tags')).toHaveTextContent('Keyingi qadam'));
    expect(screen.queryByTestId('brief-decisions-0-tags')).toBeNull();
    // Yechimsiz xavf - "Hal qilinmagan" bo'limi emas, xavfning o'z bandida chip.
    await fireEvent.press(screen.getByTestId('group-risks'));
    expect(within(screen.getByTestId('group-body-risks')).getByText('Yechim aytilmagan')).toBeTruthy();
    expect(screen.queryByTestId('section-followUps')).toBeNull();
  });

  it('short meeting: two groups, then "N more sections"; chapters (topics) go last', async () => {
    const short = meeting({ durationSec: 540 });
    const s = summary();
    s.content!.meeting = { ...s.content!.meeting, durationSec: 540 };
    s.content!.keyPoints = Array.from({ length: 5 }, (_, i) => ({ id: `K${i + 1}`, text: `Fikr ${i + 1}`, sourceSegmentIds: [1], start: i }));
    await open(fakeMeetingsApi({ get: jest.fn(async () => short), summary: jest.fn(async () => s) }));
    await waitFor(() => expect(screen.getByTestId('details')).toBeTruthy());
    // 9 daqiqa - kartada 3 ta fikr; qolgan 2 tasi "Asosiy fikrlar · 2" guruhida.
    expect(within(screen.getByTestId('brief-keyPoints')).getAllByText(/^Fikr \d\.$/)).toHaveLength(3);
    expect(screen.getByTestId('section-overview')).toBeTruthy();
    expect(screen.getByTestId('section-risks')).toBeTruthy();
    expect(screen.queryByTestId('section-topics')).toBeNull();
    expect(screen.getByTestId('details-more')).toHaveTextContent("Yana 9 ta bo'lim");
    await fireEvent.press(screen.getByTestId('details-more'));
    expect(screen.queryByTestId('details-more')).toBeNull();
    expect(screen.getByTestId('section-keyPoints')).toHaveTextContent('Asosiy fikrlar · 2');
    const json = JSON.stringify(screen.toJSON());
    expect(json.indexOf('"section-topics"')).toBeGreaterThan(json.indexOf('"section-objections"'));
    await fireEvent.press(screen.getByTestId('group-keyPoints'));
    expect(within(screen.getByTestId('group-body-keyPoints')).getByText(/Fikr 4/)).toBeTruthy();
    expect(within(screen.getByTestId('group-body-keyPoints')).queryByText(/Fikr 1/)).toBeNull();
  });

  it('no card when the summary has nothing to say', async () => {
    const empty = summary();
    const content = { ...empty.content!, purpose: null, overview: '', keyPoints: [], topics: [], decisions: [], actionItems: [], openQuestions: [] };
    // Jonli vazifalar ham yo'q - aks holda karta ularni ko'rsatardi.
    await open(fakeMeetingsApi({ summary: jest.fn(async () => ({ ...empty, content })), actionItems: jest.fn(async () => ({ items: [] })) }));
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
    expect(screen.queryByTestId('brief-card')).toBeNull();
    expect(screen.queryByText('Batafsil')).toBeNull();
  });
});

describe('mind map (Summary tab switch)', () => {
  it('lives behind the Summary | Map switch (4 main tabs); opens collapsed; a branch opens, an item seeks', async () => {
    await open();
    // Xarita 5-tab emas - tor telefonda "Vazifalar 2" kesilmasin.
    expect(screen.queryByTestId('tab-map')).toBeNull();
    expect(screen.getAllByTestId('icon-Network').length).toBeGreaterThan(0);
    await fireEvent.press(screen.getByTestId('summary-view-map'));
    await waitFor(() => expect(screen.getByTestId('mm-node-root')).toBeTruthy());
    expect(screen.getByTestId('mm-node-root').props.accessibilityLabel).toBe('Narxlar va hisobot');
    // Yig'iq ochiladi: shoxlar ko'rinadi, bandlar - shox bosilganda.
    expect(screen.queryByTestId(`mm-node-act:${AI}`)).toBeNull();
    expect(screen.getByTestId('mm-node-group:tasks').props.accessibilityLabel).toBe('Vazifalar: ochish');
    await fireEvent.press(screen.getByTestId('mm-node-group:tasks'));
    expect(screen.getByTestId(`mm-node-act:${AI}`).props.accessibilityLabel).toBe('Hisobotni yuborish, 00:09 dan eshitish');
    await fireEvent.press(screen.getByTestId(`mm-node-act:${AI}`));
    await waitFor(() => expect(player.seekTo).toHaveBeenCalledWith(9.5));
    expect(player.play).toHaveBeenCalled();
    // Pleer doim pastda.
    expect(screen.getByTestId('player-dock')).toBeTruthy();
  });

  it('follows the summary chosen on the Summary tab', async () => {
    const second = { ...summaryCard, id: 's2', template: 'short_call' as const, primary: false };
    const other = summary({ ...second, content: { ...summary().content!, title: "Qisqa qo'ng'iroq", topics: [] } });
    const api = fakeMeetingsApi({
      summaries: jest.fn(async () => ({ items: [summaryCard, second] })),
      summary: jest.fn(async (_id: string, sid: string) => (sid === 's2' ? other : summary())),
    });
    await open(api);
    await waitFor(() => expect(screen.getByTestId('summary-tab-s2')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('summary-tab-s2'));
    await waitFor(() => expect(screen.getByTestId('brief-title')).toHaveTextContent("Qisqa qo'ng'iroq"));
    await fireEvent.press(screen.getByTestId('summary-view-map'));
    await waitFor(() => expect(screen.getByTestId('mm-node-root').props.accessibilityLabel).toBe("Qisqa qo'ng'iroq"));
    // Mavzusiz qisqa qo'ng'iroq - asosiy fikrlar alohida shox.
    expect(screen.getByTestId('mm-node-group:keyPoints')).toBeTruthy();
  });

  it('shows a calm empty state while there is no summary', async () => {
    await open(fakeMeetingsApi({ get: jest.fn(async () => meeting({ summaryStatus: 'none', primarySummaryId: null })), summaries: jest.fn(async () => ({ items: [] })) }));
    await fireEvent.press(screen.getByTestId('summary-view-map'));
    await waitFor(() => expect(screen.getByTestId('mindmap-empty')).toBeTruthy());
  });
});

describe('MindMapView controls', () => {
  const root = buildMindMap(summary().content, { speakers: summary().speakers })!;

  it('opens collapsed; branches open by tap or knob (a topic with a time too); expand/collapse all', async () => {
    const onSeek = jest.fn();
    await render(<MindMapView root={root} onSeek={onSeek} />);
    expect(screen.queryByTestId('mm-node-act:A2')).toBeNull();
    expect(screen.getByTestId('mindmap-fold').props.accessibilityLabel).toBe('Hammasini ochish');
    expect(screen.getByTestId('mm-toggle-group:tasks').props.accessibilityLabel).toBe('Vazifalar: ochish');
    await fireEvent.press(screen.getByTestId('mm-toggle-group:tasks'));
    expect(screen.getByTestId('mm-node-act:A2')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('mm-node-group:tasks'));
    expect(screen.queryByTestId('mm-node-act:A2')).toBeNull();
    // Vaqti bor mavzu ham bosilganda OCHILADI (eshittirmaydi) - hamma shox bir xil ishlaydi.
    expect(screen.getByTestId('mm-node-topic:T1').props.accessibilityLabel).toBe('Narxlar: ochish');
    await fireEvent.press(screen.getByTestId('mm-node-topic:T1'));
    expect(screen.getByTestId('mm-node-topic:T1:1')).toBeTruthy();
    expect(onSeek).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId('mm-node-topic:T1:1'));
    expect(onSeek).toHaveBeenCalledWith(4.3);
    await fireEvent.press(screen.getByTestId('mindmap-fold'));
    expect(screen.getByTestId('mm-node-q:Q1')).toBeTruthy();
    expect(screen.getByTestId('mindmap-fold').props.accessibilityLabel).toBe("Hammasini yig'ish");
    await fireEvent.press(screen.getByTestId('mindmap-fold'));
    expect(screen.queryByTestId('mm-node-q:Q1')).toBeNull();
  });

  it('zooms with - / + and resets to 100%', async () => {
    await render(<MindMapView root={root} />);
    expect(screen.getByTestId('mindmap-zoom-reset')).toHaveTextContent('100%');
    await fireEvent.press(screen.getByTestId('mindmap-zoom-in'));
    expect(screen.getByTestId('mindmap-zoom-reset')).toHaveTextContent('125%');
    for (let i = 0; i < 8; i++) await fireEvent.press(screen.getByTestId('mindmap-zoom-out'));
    expect(screen.getByTestId('mindmap-zoom-reset')).toHaveTextContent('50%');
    expect(screen.getByTestId('mindmap-zoom-out')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('mindmap-zoom-reset'));
    expect(screen.getByTestId('mindmap-zoom-reset')).toHaveTextContent('100%');
  });

  it('outline mode lists the same tree; rows seek and fold', async () => {
    const onSeek = jest.fn();
    await render(<MindMapView root={root} onSeek={onSeek} />);
    await fireEvent.press(screen.getByTestId('mindmap-mode-outline'));
    expect(screen.getByTestId('mindmap-outline')).toBeTruthy();
    expect(screen.queryByTestId('mindmap-canvas')).toBeNull();
    expect(screen.getByText('Narxlar va hisobot')).toBeTruthy();
    // Yig'iq: shox qatori bosilsa ochiladi.
    expect(screen.queryByTestId('mm-row-q:Q1')).toBeNull();
    await fireEvent.press(screen.getByTestId('mm-row-group:questions'));
    expect(screen.getByTestId('mm-row-q:Q1')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('mindmap-fold'));
    expect(screen.getByText('2-ishtirokchi · Muddat: 10-oktabr · ▶ 00:09')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('mm-row-q:Q1'));
    expect(onSeek).toHaveBeenCalledWith(15.2);
    expect(screen.getByTestId('mm-row-q:Q1').props.accessibilityState).toMatchObject({ selected: true });
    await fireEvent.press(screen.getByTestId('mm-row-toggle-group:decisions'));
    expect(screen.queryByTestId('mm-row-dec:D1')).toBeNull();
    // Holat umumiy: xaritaga qaytganda ham yig'ilgan.
    await fireEvent.press(screen.getByTestId('mindmap-mode-map'));
    expect(screen.queryByTestId('mm-node-dec:D1')).toBeNull();
    expect(screen.getByTestId('mm-node-group:decisions')).toBeTruthy();
  });
});

describe('export entry point', () => {
  it('the header share icon and the ⋮ menu open the export sheet for this meeting', async () => {
    await open(fakeMeetingsApi(), { withHeader: true });
    await waitFor(() => expect(screen.getByTestId('meeting-export')).toBeTruthy());
    expect(screen.queryByTestId('export-sheet')).toBeNull();
    await fireEvent.press(screen.getByTestId('meeting-export'));
    expect(screen.getByTestId('export-sheet')).toHaveTextContent(`${ID}|Yig'ilish 9-oktyabr, 11:00|true|-`);
    await fireEvent.press(screen.getByTestId('export-sheet')); // onClose
    expect(screen.queryByTestId('export-sheet')).toBeNull();
    await fireEvent.press(screen.getByTestId('meeting-menu'));
    await fireEvent.press(screen.getByTestId('menu-export'));
    await waitFor(() => expect(screen.getByTestId('export-sheet')).toBeTruthy());
  });

  it('exports the summary being viewed (another template), not always the primary one', async () => {
    const second = { ...summaryCard, id: 's2', template: 'short_call' as const, primary: false };
    const api = fakeMeetingsApi({
      summaries: jest.fn(async () => ({ items: [summaryCard, second] })),
      summary: jest.fn(async (_id: string, sid: string) => (sid === 's2' ? summary({ ...second }) : summary())),
    });
    await open(api, { withHeader: true });
    await waitFor(() => expect(screen.getByTestId('summary-tab-s2')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('summary-tab-s2'));
    await fireEvent.press(screen.getByTestId('meeting-export'));
    expect(screen.getByTestId('export-sheet')).toHaveTextContent(`${ID}|Yig'ilish 9-oktyabr, 11:00|true|s2`);
  });
});
