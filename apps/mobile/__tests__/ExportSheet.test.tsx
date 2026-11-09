/**
 * Ulashish va eksport varag'i: format + qismlar -> `GET /meetings/{id}/export` (yoki audio
 * `?download=1`) `Authorization` bilan keshga -> Android ulashish oynasi. Xatolar sababi
 * bilan: 409 (faqat transkript), 503 pdf_unavailable (Word'da), 429/503 band, internet yo'q,
 * yuklash uzilib qoldi (qo'riqchi), 410 (qayta urinish yo'q). Standart tarkib - Qisqa xulosa,
 * To'liq xulosa, Vazifalar. "Subtitr (SRT)" - faqat transkript (`/transcript/export?format=srt`). Native qatlam (expo-file-system/legacy, expo-sharing) - soxta;
 * tarmoq yo'q.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import { ApiClient, ApiError, AuthRequiredError, type TokenProvider } from '@/api/client';
import {
  createMeetingsApi,
  downloadWithAuth,
  exportPartsParam,
  fileNameFromDisposition,
  safeFileName,
  type FileDownloader,
} from '@/api/meetings';
import { DEFAULT_EXPORT_PARTS, defaultParts, ExportSheet, resetExportMemory, shareProblem } from '@/features/meeting/ExportSheet';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';

// `createDownloadResumable` soxtasi: har yuklash `downloadAsync(url, fileUri, opts, onProgress)`
// "server"iga boradi (testlar javobni shu yerda beradi), `cancelAsync` - bekor qilish.
jest.mock('expo-file-system/legacy', () => {
  const downloadAsync = jest.fn();
  const cancelAsync = jest.fn(async () => {});
  return {
    cacheDirectory: 'file:///cache/',
    downloadAsync,
    cancelAsync,
    createDownloadResumable: jest.fn((url: string, fileUri: string, opts: unknown, onProgress?: unknown) => ({
      downloadAsync: () => downloadAsync(url, fileUri, opts, onProgress),
      cancelAsync,
    })),
    readAsStringAsync: jest.fn(async () => ''),
    deleteAsync: jest.fn(async () => {}),
    makeDirectoryAsync: jest.fn(async () => {}),
    moveAsync: jest.fn(async () => {}),
  };
});
jest.mock('expo-sharing', () => ({
  isAvailableAsync: jest.fn(async () => true),
  shareAsync: jest.fn(async () => {}),
}));
jest.mock('expo-network', () => ({
  getNetworkStateAsync: jest.fn(async () => ({ isConnected: true, isInternetReachable: true })),
  addNetworkStateListener: jest.fn(() => ({ remove: jest.fn() })),
}));

type Downloaded = { status: number; uri: string; headers: Record<string, string> };
type Progress = (p: { totalBytesWritten: number; totalBytesExpectedToWrite: number }) => void;
const FS = jest.requireMock('expo-file-system/legacy') as {
  downloadAsync: jest.Mock<Promise<Downloaded>, [string, string, { headers: Record<string, string> }, Progress | undefined]>;
  cancelAsync: jest.Mock;
  readAsStringAsync: jest.Mock<Promise<string>, [string]>;
  deleteAsync: jest.Mock;
  makeDirectoryAsync: jest.Mock;
  moveAsync: jest.Mock;
};
const Sharing = jest.requireMock('expo-sharing') as { isAvailableAsync: jest.Mock; shareAsync: jest.Mock };
const Network = jest.requireMock('expo-network') as { getNetworkStateAsync: jest.Mock };

const ID = 'a'.repeat(32);
const BASE = `https://x.uz/api/v1/meetings/${ID}`;
/** Standart tarkib: xarita va transkript - odam o'zi yoqsa. */
const DEF = 'brief%2Csummary%2Cactions';
const PDF_NAME = "Narxlar va hisobot 2026-10-10.pdf";
const PDF_HEADERS = {
  'Content-Type': 'application/pdf',
  'Content-Disposition': `attachment; filename="narxlar-va-hisobot-2026-10-10.pdf"; filename*=UTF-8''${encodeURIComponent(PDF_NAME)}`,
};

/** Javob: 2xx - fayl, aks holda tana (server konverti) shu faylda turadi. */
function respond(status: number, headers: Record<string, string> = {}, body = '') {
  FS.downloadAsync.mockImplementationOnce(async (_url, fileUri) => {
    if (body) FS.readAsStringAsync.mockResolvedValueOnce(body);
    return { status, uri: fileUri, headers };
  });
}

function envelope(status: number, code: string, extra: Record<string, unknown> = {}) {
  return JSON.stringify({ status, code, message: code, ...extra });
}

function services() {
  const real = createMeetingsApi(new ApiClient({ baseUrl: 'https://x.uz/' }));
  return fakeServices({
    meetings: fakeMeetingsApi({ exportUrl: real.exportUrl, audioDownloadUrl: real.audioDownloadUrl, transcriptExportUrl: real.transcriptExportUrl }),
  });
}

async function open(props: { hasSummary?: boolean; format?: 'pdf' | 'docx' | 'md' | 'txt' | 'srt' | 'audio'; summaryId?: string } = {}) {
  const onClose = jest.fn();
  const svc = services();
  const view = await render(
    <Providers services={svc}>
      <ExportSheet visible onClose={onClose} meetingId={ID} title="Narxlar va hisobot" hasSummary={props.hasSummary ?? true} summaryId={props.summaryId} />
    </Providers>,
  );
  // Format modul darajasida eslab qolinadi (oxirgi tanlov) - testlar bir-biriga bog'liq bo'lmasin.
  await fireEvent.press(screen.getByTestId(`export-fmt-${props.format ?? 'pdf'}`));
  return { onClose, svc, view };
}

async function share() {
  await act(async () => {
    await fireEvent.press(screen.getByTestId('export-share'));
  });
}

const url = (i = 0) => FS.downloadAsync.mock.calls[i][0];

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
  resetExportMemory();
  FS.downloadAsync.mockReset();
  FS.cancelAsync.mockClear();
  FS.readAsStringAsync.mockReset();
  FS.readAsStringAsync.mockResolvedValue('');
  Sharing.isAvailableAsync.mockResolvedValue(true);
  Network.getNetworkStateAsync.mockResolvedValue({ isConnected: true, isInternetReachable: true });
});

describe('ExportSheet', () => {
  it('PDF with the default parts: auth download into the cache, real file name, Android share sheet, then closes', async () => {
    const { onClose } = await open();
    expect(screen.getByTestId('export-fmt-pdf')).toBeChecked();
    expect(screen.getByTestId('export-fmt-docx')).not.toBeChecked();
    // Standart: rahbarga yuboriladigan qism; 20+ sahifalik transkript va xarita - o'zi yoqsa.
    for (const p of ['brief', 'summary', 'actions']) expect(screen.getByTestId(`export-part-${p}`)).toBeChecked();
    for (const p of ['mindmap', 'transcript']) expect(screen.getByTestId(`export-part-${p}`)).not.toBeChecked();
    expect(screen.getByText("To'liq xulosa")).toBeTruthy();
    respond(200, PDF_HEADERS);
    await share();

    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url()).toBe(`${BASE}/export?format=pdf&parts=${DEF}`);
    const [, tmp, opts] = FS.downloadAsync.mock.calls[0];
    expect(tmp).toMatch(/^file:\/\/\/cache\/exports\/download-\d+\.part$/);
    expect(opts.headers).toMatchObject({ Authorization: 'Bearer jwt', 'X-Venera-Client': 'mobile', 'Accept-Language': 'uz' });
    // Oldingi eksportlar keyingi eksportda tozalanadi.
    expect(FS.deleteAsync).toHaveBeenCalledWith('file:///cache/exports/', { idempotent: true });
    expect(FS.makeDirectoryAsync).toHaveBeenCalledWith('file:///cache/exports/', { intermediates: true });
    const target = `file:///cache/exports/${encodeURIComponent(PDF_NAME)}`;
    expect(FS.moveAsync).toHaveBeenCalledWith({ from: tmp, to: target });
    expect(Sharing.shareAsync).toHaveBeenCalledWith(target, { mimeType: 'application/pdf', dialogTitle: 'Narxlar va hisobot' });
    expect(onClose).toHaveBeenCalled();
  });

  it('no summary yet: summary parts are off and disabled, only the transcript is requested', async () => {
    await open({ hasSummary: false, format: 'docx' });
    for (const p of ['brief', 'summary', 'actions', 'mindmap']) {
      expect(screen.getByTestId(`export-part-${p}`)).not.toBeChecked();
      expect(screen.getByTestId(`export-part-${p}`)).toBeDisabled();
    }
    expect(screen.getByTestId('export-part-transcript')).toBeChecked();
    expect(screen.getByTestId('export-part-transcript')).not.toBeDisabled();
    expect(screen.getByText("Xulosa tayyor bo'lgach qo'shiladi")).toBeTruthy();
    respond(200, { 'Content-Disposition': 'attachment; filename="narxlar.docx"' });
    await share();
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url()).toBe(`${BASE}/export?format=docx&parts=transcript`);
    expect(Sharing.shareAsync.mock.calls[0][1].mimeType).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    expect(Sharing.shareAsync.mock.calls[0][0]).toBe('file:///cache/exports/narxlar.docx');
  });

  it('parts can be turned on/off (and are remembered); with nothing picked "Ulashish" is disabled and says why', async () => {
    await open({ format: 'md' });
    await fireEvent.press(screen.getByTestId('export-part-mindmap'));
    await fireEvent(screen.getByTestId('export-part-transcript-switch'), 'valueChange', true);
    await fireEvent.press(screen.getByTestId('export-part-summary'));
    // Keyingi ochilishda shu tanlov (ilova ochiq turganda).
    expect(defaultParts(true)).toEqual(['brief', 'actions', 'mindmap', 'transcript']);
    respond(200, { 'Content-Disposition': 'attachment; filename="x.md"' });
    await share();
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url()).toBe(`${BASE}/export?format=md&parts=brief%2Cactions%2Cmindmap%2Ctranscript`);
    expect(Sharing.shareAsync.mock.calls[0][1].mimeType).toBe('text/markdown');

    for (const p of ['brief', 'actions', 'mindmap', 'transcript']) await fireEvent.press(screen.getByTestId(`export-part-${p}`));
    expect(screen.getByText('Kamida bitta qismni tanlang')).toBeTruthy();
    expect(screen.getByTestId('export-share')).toBeDisabled();
  });

  it('exports the summary being viewed (summaryId)', async () => {
    await open({ summaryId: 's2' });
    respond(200, PDF_HEADERS);
    await share();
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url()).toBe(`${BASE}/export?format=pdf&parts=${DEF}&summaryId=s2`);
  });

  it('409 not_ready: says the summary is not ready and "Faqat transkript" retries with the transcript only', async () => {
    await open({ format: 'txt' });
    respond(409, {}, envelope(409, 'not_ready', { missing: ['brief', 'summary', 'actions', 'mindmap'], available: ['transcript'] }));
    await share();
    expect(await screen.findByText('Xulosa hali tayyor emas')).toBeTruthy();
    // Xato tanasi o'qilgach vaqtinchalik fayl o'chiriladi; ulashish oynasi ochilmaydi.
    expect(FS.deleteAsync).toHaveBeenCalledWith(FS.downloadAsync.mock.calls[0][1], { idempotent: true });
    expect(Sharing.shareAsync).not.toHaveBeenCalled();

    respond(200, { 'Content-Disposition': 'attachment; filename="x.txt"', 'Content-Type': 'text/plain; charset=utf-8' });
    await act(async () => {
      await fireEvent.press(screen.getByText('Faqat transkript'));
    });
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url(1)).toBe(`${BASE}/export?format=txt&parts=transcript`);
    expect(screen.getByTestId('export-part-brief')).not.toBeChecked();
    expect(screen.getByTestId('export-part-transcript')).toBeChecked();
  });

  it('409 with nothing ready: no transcript-only offer', async () => {
    await open();
    respond(409, {}, envelope(409, 'not_ready', { available: [] }));
    await share();
    expect(await screen.findByText("Yozuv hali matnga o'girilmagan - tayyor bo'lgach ulashing")).toBeTruthy();
    expect(screen.queryByText('Faqat transkript')).toBeNull();
  });

  it('503 pdf_unavailable: "Word\'da ulashish" switches to DOCX and shares', async () => {
    await open();
    respond(503, { 'Retry-After': '10' }, envelope(503, 'pdf_unavailable'));
    await share();
    expect(await screen.findByText("PDF hozircha tayyorlab bo'lmaydi")).toBeTruthy();
    respond(200, { 'Content-Disposition': 'attachment; filename="x.docx"' });
    await act(async () => {
      await fireEvent.press(screen.getByText("Word'da ulashish"));
    });
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url(1)).toBe(`${BASE}/export?format=docx&parts=${DEF}`);
    expect(screen.getByTestId('export-fmt-docx')).toBeChecked();
  });

  it('busy and limits: 429/503 export_busy offer a retry, 429 rate_limited names the hourly limit', async () => {
    await open();
    respond(429, { 'Retry-After': '5' }, envelope(429, 'export_busy'));
    await share();
    expect(await screen.findByText("Oldingi fayl hali tayyorlanmoqda - birozdan keyin qayta urinib ko'ring")).toBeTruthy();

    respond(503, {}, envelope(503, 'export_busy'));
    await act(async () => {
      await fireEvent.press(screen.getByText('Qayta urinish'));
    });
    expect(await screen.findByText("Server band - birozdan keyin qayta urinib ko'ring")).toBeTruthy();
    expect(url(1)).toBe(`${BASE}/export?format=pdf&parts=${DEF}`);

    respond(429, {}, envelope(429, 'rate_limited'));
    await act(async () => {
      await fireEvent.press(screen.getByText('Qayta urinish'));
    });
    expect(await screen.findByText("Bir soatlik fayl chegarasi tugadi - keyinroq urinib ko'ring")).toBeTruthy();
    expect(screen.queryByText('Qayta urinish')).toBeNull();
    expect(Sharing.shareAsync).not.toHaveBeenCalled();
  });

  it('offline: a failed download says "Internet yo\'q" and offers a retry', async () => {
    await open();
    FS.downloadAsync.mockRejectedValueOnce(new Error('Unable to resolve host "x.uz"'));
    await share();
    expect(await screen.findByTestId('export-problem')).toHaveTextContent(/^Internet yo'q\. Fayl serverda tayyorlanadi/);
    expect(screen.getByText('Qayta urinish')).toBeTruthy();
    expect(screen.getByTestId('export-share')).not.toBeDisabled();
  });

  it('offline phone: warning banner without pressing anything', async () => {
    Network.getNetworkStateAsync.mockResolvedValue({ isConnected: false, isInternetReachable: false });
    await open();
    expect(await screen.findByTestId('export-offline')).toHaveTextContent(/^Internet yo'q/);
  });

  it('audio file: /audio?download=1, no parts, progress, name and MIME from the response', async () => {
    await open({ format: 'audio' });
    expect(screen.queryByTestId('export-part-brief')).toBeNull();
    let finish: () => void = () => {};
    FS.downloadAsync.mockImplementationOnce(
      (_url, fileUri, _opts, onProgress) =>
        new Promise<Downloaded>((resolve) => {
          onProgress?.({ totalBytesWritten: 42, totalBytesExpectedToWrite: 100 });
          finish = () =>
            resolve({
              status: 200,
              uri: fileUri,
              headers: { 'content-type': 'audio/mp4', 'content-disposition': `attachment; filename="narxlar.m4a"; filename*=UTF-8''Narxlar%202026-10-10.m4a` },
            });
        }),
    );
    await share();
    // O'nlab MB audio - odam qancha qolganini ko'radi.
    expect(screen.getByTestId('export-status')).toHaveTextContent('Yuklanmoqda: 42%');
    await act(async () => finish());
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url()).toBe(`${BASE}/audio?download=1`);
    expect(Sharing.shareAsync).toHaveBeenCalledWith('file:///cache/exports/Narxlar%202026-10-10.m4a', { mimeType: 'audio/mp4', dialogTitle: 'Narxlar va hisobot' });
  });

  it('Subtitr (SRT): transcript only via /transcript/export?format=srt - no parts, a .srt subrip file', async () => {
    const { onClose } = await open({ format: 'srt' });
    expect(screen.getByTestId('export-fmt-srt')).toBeChecked();
    expect(screen.getByText('Subtitr (SRT)')).toBeTruthy();
    expect(screen.getByText('Faqat transkript, vaqt belgilari bilan')).toBeTruthy();
    // Qismlar subtitrga taalluqli emas.
    expect(screen.queryByTestId('export-part-brief')).toBeNull();
    expect(screen.queryByTestId('export-part-transcript')).toBeNull();
    respond(200, { 'Content-Type': 'application/x-subrip; charset=utf-8', 'Content-Disposition': 'attachment; filename="narxlar-va-hisobot.srt"' });
    await share();
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(url()).toBe(`${BASE}/transcript/export?format=srt`);
    expect(FS.downloadAsync.mock.calls[0][2].headers).toMatchObject({ Authorization: 'Bearer jwt' });
    expect(Sharing.shareAsync).toHaveBeenCalledWith('file:///cache/exports/narxlar-va-hisobot.srt', {
      mimeType: 'application/x-subrip',
      dialogTitle: 'Narxlar va hisobot',
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('SRT before the transcript is ready: 409 says so honestly, no "transcript only" offer', async () => {
    await open({ format: 'srt', hasSummary: false });
    respond(409, {}, envelope(409, 'not_ready'));
    await share();
    expect(await screen.findByText("Yozuv hali matnga o'girilmagan - tayyor bo'lgach ulashing")).toBeTruthy();
    expect(screen.queryByText('Faqat transkript')).toBeNull();
    expect(shareProblem(new ApiError(409, 'not_ready', 'x', { available: ['transcript'] }), 'srt', ['brief'])).toEqual({
      kind: 'notReady',
      audio: false,
      nothing: true,
      transcriptOnly: false,
    });
  });

  it('audio of an mp3/wav/ogg meeting keeps its real extension and MIME (not "x.mp3.m4a")', async () => {
    for (const [type, file] of [
      ['audio/mpeg', 'Kengash 9-noyabr.mp3'],
      ['audio/wav', 'Diktofon.wav'],
      ['audio/ogg', 'Ovozli xabar.ogg'],
    ] as const) {
      Sharing.shareAsync.mockClear();
      FS.downloadAsync.mockReset();
      await open({ format: 'audio' });
      respond(200, { 'Content-Type': type, 'Content-Disposition': `attachment; filename="a"; filename*=UTF-8''${encodeURIComponent(file)}` });
      await share();
      await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
      expect(Sharing.shareAsync).toHaveBeenCalledWith(`file:///cache/exports/${encodeURIComponent(file)}`, { mimeType: type, dialogTitle: 'Narxlar va hisobot' });
      await screen.unmount();
    }
  });

  it('410 audio_expired is explained WITHOUT a useless retry; a phone without a share target says so', async () => {
    await open({ format: 'audio' });
    respond(410, {}, envelope(410, 'audio_expired'));
    await share();
    expect(await screen.findByText("Audio serverda saqlanmagan (saqlash muddati o'tgan) - matnli faylni ulashing")).toBeTruthy();
    expect(screen.queryByText('Qayta urinish')).toBeNull();

    Sharing.isAvailableAsync.mockResolvedValueOnce(false);
    await share();
    expect(await screen.findByText("Bu telefonda fayl ulashib bo'lmaydi")).toBeTruthy();
    expect(FS.downloadAsync).toHaveBeenCalledTimes(1);
  });

  it('closing while the file is being prepared never opens the share sheet later', async () => {
    const { svc, view } = await open();
    let finish: (v: Downloaded) => void = () => {};
    FS.downloadAsync.mockImplementationOnce((_u, fileUri) => new Promise<Downloaded>((r) => (finish = (v) => r({ ...v, uri: fileUri }))));
    await share();
    expect(screen.getByText('Fayl tayyorlanmoqda...')).toBeTruthy();
    await view.rerender(
      <Providers services={svc}>
        <ExportSheet visible={false} onClose={() => {}} meetingId={ID} title="Narxlar va hisobot" hasSummary />
      </Providers>,
    );
    // Yopilganda native yuklash ham bekor qilinadi (o'nlab MB fonda yuklanib yotmasin).
    expect(FS.cancelAsync).toHaveBeenCalled();
    await act(async () => {
      finish({ status: 200, uri: '', headers: PDF_HEADERS });
    });
    expect(Sharing.shareAsync).not.toHaveBeenCalled();
  });

  it('defaultParts: summary-less meetings share the transcript only; a remembered choice wins', () => {
    expect(defaultParts(false)).toEqual(['transcript']);
    expect(defaultParts(true, null)).toEqual([...DEFAULT_EXPORT_PARTS]);
    expect(defaultParts(true, ['transcript'])).toEqual(['transcript']);
  });
});

describe('export API helpers', () => {
  const tp = (): jest.Mocked<TokenProvider> => ({ getToken: jest.fn(async () => 'tok'), refreshToken: jest.fn(async () => 'tok2') });
  const io = (results: (Downloaded | Error)[], body = ''): jest.Mocked<FileDownloader> => ({
    download: jest.fn(async (_u: string, fileUri: string, _h: Record<string, string>) => {
      const r = results.shift();
      if (r instanceof Error) throw r;
      return { ...(r as Downloaded), uri: fileUri };
    }),
    readText: jest.fn(async (_uri: string) => body),
    remove: jest.fn(async (_uri: string) => {}),
  });

  it('URL builders: export parts in server order, summaryId, audio download flag', () => {
    const m = createMeetingsApi(new ApiClient({ baseUrl: 'https://llm.brb-tech.uz/' }));
    expect(m.exportUrl(ID, { format: 'pdf' })).toBe(`https://llm.brb-tech.uz/api/v1/meetings/${ID}/export?format=pdf`);
    expect(m.exportUrl(ID, { format: 'docx', parts: ['transcript', 'brief', 'transcript'], summaryId: 'S1' })).toBe(
      `https://llm.brb-tech.uz/api/v1/meetings/${ID}/export?format=docx&parts=brief%2Ctranscript&summaryId=S1`,
    );
    expect(m.audioDownloadUrl(ID)).toBe(`https://llm.brb-tech.uz/api/v1/meetings/${ID}/audio?download=1`);
    expect(exportPartsParam([])).toBeUndefined();
    expect(exportPartsParam(null)).toBeUndefined();
  });

  it('file names: real UTF-8 name first, then ASCII, then the title; unsafe characters and extension handled', () => {
    expect(fileNameFromDisposition(`attachment; filename="a.pdf"; filename*=UTF-8''${encodeURIComponent("Yig'ilish: reja/2026.pdf")}`, 'T', 'pdf')).toBe(
      "Yig'ilish reja 2026.pdf",
    );
    expect(fileNameFromDisposition('attachment; filename="narxlar-2026-10-10.docx"', 'T', 'docx')).toBe('narxlar-2026-10-10.docx');
    expect(fileNameFromDisposition("attachment; filename*=UTF-8''%E0%A4%A", 'Haftalik reja', 'md')).toBe('Haftalik reja.md');
    expect(fileNameFromDisposition(null, '', 'txt')).toBe('Barno AI.txt');
    expect(fileNameFromDisposition('attachment; filename="Отчёт"', 'T', 'pdf')).toBe('Отчёт.pdf');
    const long = safeFileName('x'.repeat(300), 'pdf');
    expect([long.length, long.endsWith('.pdf')]).toEqual([100, true]);
  });

  it('downloadWithAuth: 401 refreshes the token ONCE and retries', async () => {
    const tokens = tp();
    const fake = io([{ status: 401, uri: '', headers: {} }, { status: 200, uri: '', headers: { 'Content-Type': 'application/pdf' } }]);
    const res = await downloadWithAuth('https://x/f', 'file:///c/f', { tokens, io: fake, language: 'ru' });
    expect(res.status).toBe(200);
    expect(tokens.refreshToken).toHaveBeenCalledTimes(1);
    expect(fake.download.mock.calls[0][2]).toMatchObject({ Authorization: 'Bearer tok', 'Accept-Language': 'ru' });
    expect(fake.download.mock.calls[1][2]).toMatchObject({ Authorization: 'Bearer tok2' });
  });

  it('downloadWithAuth: error envelope -> ApiError with code, body and Retry-After; temp file removed', async () => {
    const fake = io([{ status: 409, uri: '', headers: { 'retry-after': '7' } }], envelope(409, 'not_ready', { available: ['transcript'] }));
    const err = await downloadWithAuth('https://x/f', 'file:///c/f', { tokens: tp(), io: fake }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: 'not_ready', retryAfterSec: 7 });
    expect((err as ApiError).body?.available).toEqual(['transcript']);
    expect(fake.remove).toHaveBeenCalledWith('file:///c/f');
    expect(shareProblem(err, 'pdf', ['brief', 'transcript'])).toEqual({ kind: 'notReady', audio: false, nothing: false, transcriptOnly: true });
    // Faqat transkript so'ralgan bo'lsa "faqat transkript" taklif qilinmaydi.
    expect(shareProblem(err, 'pdf', ['transcript'])).toMatchObject({ transcriptOnly: false });
  });

  it('downloadWithAuth: an HTML error page falls back to the status code; network failure is status 0', async () => {
    const html = io([{ status: 502, uri: '', headers: {} }], '<html>Bad Gateway</html>');
    await expect(downloadWithAuth('https://x/f', 'file:///c/f', { tokens: tp(), io: html })).rejects.toMatchObject({ status: 502, code: 'bad_gateway' });
    const off = io([new Error('timeout')]);
    const err = await downloadWithAuth('https://x/f', 'file:///c/f', { tokens: tp(), io: off }).catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 0, code: 'network' });
    expect(off.remove).toHaveBeenCalledWith('file:///c/f');
    expect(shareProblem(err, 'pdf', [])).toEqual({ kind: 'offline' });
  });

  it('downloadWithAuth: a download that never finishes is cancelled by the stall watchdog (retryable)', async () => {
    let signal: AbortSignal | undefined;
    const hang: jest.Mocked<FileDownloader> = {
      download: jest.fn((_u: string, _f: string, _h: Record<string, string>, c?: { signal?: AbortSignal }) => {
        signal = c?.signal;
        return new Promise<never>(() => {});
      }),
      readText: jest.fn(async (_uri: string) => ''),
      remove: jest.fn(async (_uri: string) => {}),
    };
    const err = await downloadWithAuth('https://x/f', 'file:///c/f', { tokens: tp(), io: hang, firstByteMs: 20 }).catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 0, code: 'stalled' });
    expect(signal?.aborted).toBe(true); // native yuklash bekor qilindi
    expect(hang.remove).toHaveBeenCalledWith('file:///c/f');
    expect(shareProblem(err, 'audio', [])).toEqual({ kind: 'stalled' });
  });

  it('downloadWithAuth: progress keeps a slow download alive; an outside abort stops it', async () => {
    const slow: jest.Mocked<FileDownloader> = {
      download: jest.fn(
        (_u: string, fileUri: string, _h: Record<string, string>, c?: { onProgress?: (p: { written: number; total: number }) => void }) =>
          new Promise<Downloaded>((resolve) => {
            let n = 0;
            const tick = setInterval(() => {
              n += 1;
              c?.onProgress?.({ written: n, total: 6 });
              if (n === 6) {
                clearInterval(tick);
                resolve({ status: 200, uri: fileUri, headers: {} });
              }
            }, 10);
          }),
      ),
      readText: jest.fn(async (_uri: string) => ''),
      remove: jest.fn(async (_uri: string) => {}),
    };
    const seen: number[] = [];
    const res = await downloadWithAuth('https://x/f', 'file:///c/f', { tokens: tp(), io: slow, firstByteMs: 30, stallMs: 30, onProgress: (p) => seen.push(p.written) });
    expect(res.status).toBe(200); // 60 ms davom etdi, lekin har 10 ms da bayt keldi
    expect(seen).toEqual([1, 2, 3, 4, 5, 6]);

    const ctl = new AbortController();
    const hang: jest.Mocked<FileDownloader> = {
      download: jest.fn((_u: string, _f: string, _h: Record<string, string>) => new Promise<never>(() => {})),
      readText: jest.fn(async (_uri: string) => ''),
      remove: jest.fn(async (_uri: string) => {}),
    };
    const pending = downloadWithAuth('https://x/f', 'file:///c/f', { tokens: tp(), io: hang, signal: ctl.signal }).catch((e: unknown) => e);
    await Promise.resolve();
    ctl.abort();
    expect(await pending).toMatchObject({ status: 0, code: 'aborted' });
  });

  it('final errors (403/404/410 on a document) offer no retry', () => {
    expect(shareProblem(new ApiError(404, 'not_found', 'x'), 'pdf', ['brief'])).toMatchObject({ kind: 'final' });
    expect(shareProblem(new ApiError(410, 'gone', 'x'), 'pdf', ['brief'])).toMatchObject({ kind: 'final' });
    expect(shareProblem(new ApiError(410, 'audio_expired', 'x'), 'audio', [])).toEqual({ kind: 'audioExpired' });
  });

  it('downloadWithAuth: no session -> AuthRequiredError (no refresh loop)', async () => {
    const tokens = tp();
    tokens.getToken.mockRejectedValueOnce(new AuthRequiredError());
    await expect(downloadWithAuth('https://x/f', 'file:///c/f', { tokens, io: io([]) })).rejects.toBeInstanceOf(AuthRequiredError);
    expect(tokens.refreshToken).not.toHaveBeenCalled();
  });

  it('sheet styles: the share button is a pill with an icon (one tap to share)', async () => {
    await open();
    const btn = screen.getByTestId('export-share');
    expect(StyleSheet.flatten(btn.props.style)).toMatchObject({ borderRadius: 999 });
    expect(screen.getByTestId('icon-Share2')).toBeTruthy();
  });
});
