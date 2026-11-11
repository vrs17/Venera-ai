/**
 * Yozuv sahifasidagi Chat tabi (`ChatView`) - bitta yozuv bo'yicha Barno bilan suhbat: tarix eskidan
 * yangiga (savol o'ngda, javob `[S#]` -> ism, manba chiplari pleerni siljitadi, takliflar faqat oxirgi
 * javob ostida), optimistik yuborish ("Barno yozmoqda…", ikki marta yuborilmaydi, tab almashsa ham
 * yo'qolmaydi), har xabar o'z kaliti (`clientId`) bilan va "Qayta yuborish" o'sha kalit bilan, xato +
 * "Qayta yuborish", javobi yo'lda yo'qolgan, lekin server saqlagan xabar (shu kalitli savol-javob
 * kelsa xato yoki kutish yo'qoladi, takror yaratilmaydi; noma'lum xatodan ~8 s keyin tarix yana
 * o'qiladi), "Yangi suhbat" (tasdiq bilan), bo'sh holat va tezkor savollar, matn tayyor emas / eski
 * server / yozuv topilmadi (istalgan chat so'rovida). Soxta API - xotiradagi chat (`chatBackend`,
 * kalit bo'yicha takrorni serverdek qaytaradi); tarmoqqa chiqmaydi.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, renderHook, screen, waitFor, within } from '@testing-library/react-native';
import { renderRouter } from 'expo-router/testing-library';
import type { ReactNode } from 'react';
import { Alert, type AlertButton } from 'react-native';
import * as ExpoAudio from 'expo-audio';

import { ApiError } from '@/api/client';
import type { MeetingsApi } from '@/api/meetings';
import type { ChatRequest, ChatTurn } from '@/api/types';
import MeetingRoute from '@/app/meeting/[id]';
import { CHAT_RECHECK_MS } from '@/features/meeting/chatModel';
import { chatSendKey, isChatSending, useChatOutgoing } from '@/features/meeting/queries';
import { useSettings } from '@/features/settings/settingsStore';

import { chatEndpoints, fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { chatBackend, chatTurn, meeting } from './fixtures/server';

const ID = 'a'.repeat(32);
const T1 = chatTurn({ id: '1'.repeat(32), question: 'Kim hisobot yuboradi?' });
// Telegram'da berilgan savol ham shu suhbatda (kanaldan qat'i nazar bitta suhbat).
const T2 = chatTurn({
  id: '2'.repeat(32),
  question: 'Batafsilroq?',
  answer: '**PDF** hisobotni [S1] tekshiradi.',
  citations: [{ segmentId: 2, start: 4.3, speaker: 'S1', text: "Bugun narxlarni ko'ramiz." }],
  followUps: ['Muddat?', 'Kim tasdiqlaydi?', 'Qaysi format?'],
  channel: 'telegram',
});
/** `chatBackend` dagi n-chi yangi savol-javob id'si. */
const turnId = (n: number) => `t${n}`.padEnd(32, '0');
/** Serverning 404 konverti (`core/errors.py`): yo'l topilmasa (eski server) - `code` yo'q. */
const routeMissing = { timestamp: '2026-11-11T06:00:00Z', status: 404, error: 'Not Found', message: 'Not Found', path: `/api/v1/meetings/${ID}/chat` };
/** Yozuv o'chirilgan yoki begona: o'sha konvert, lekin `code: not_found` bilan. */
const recordingGone = () => new ApiError(404, 'not_found', "Yig'ilish topilmadi", { ...routeMissing, message: "Yig'ilish topilmadi", code: 'not_found' });
/** Xabar kaliti (`newChatClientId`): UUID v4 - server qoidasi `[A-Za-z0-9_-]{8,64}` ga ham mos. */
const KEY = expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
/** Har yuborishning kaliti (tartib bilan). */
const sentKeys = (api: jest.Mocked<MeetingsApi>) => api.sendChat.mock.calls.map((c) => c[1].clientId);

const player = (ExpoAudio as unknown as { __player: { seekTo: jest.Mock } }).__player;

function deferred() {
  let release: () => void = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

/** `over` - API o'rnini bosuvchilar; funksiya bo'lsa xotiradagi chatni oladi (sekin yoki xato beradigan o'qish uchun). */
async function openChat(
  o: { seed?: ChatTurn[]; over?: Partial<MeetingsApi> | ((chat: ReturnType<typeof chatBackend>) => Partial<MeetingsApi>) } = {},
) {
  const chat = chatBackend({ [ID]: o.seed ?? [T1, T2] });
  const over = typeof o.over === 'function' ? o.over(chat) : o.over;
  const api = fakeMeetingsApi({ ...chatEndpoints(chat), ...over });
  const services = fakeServices({ meetings: api });
  const wrapper = ({ children }: { children: ReactNode }) => <Providers services={services}>{children}</Providers>;
  await renderRouter({ 'meeting/[id]': MeetingRoute }, { initialUrl: `/meeting/${ID}`, wrapper });
  await waitFor(() => expect(screen.getByTestId('meeting-title')).toBeTruthy());
  await fireEvent.press(screen.getByTestId('tab-chat'));
  return { api, chat };
}

/** Javobni test o'zi qo'yib yuboradi: shu paytgacha xabar "yuborilmoqda". */
function holdNextSend(api: jest.Mocked<MeetingsApi>, chat: ReturnType<typeof chatBackend>) {
  const gate = deferred();
  api.sendChat.mockImplementationOnce(async (id: string, body: ChatRequest) => {
    await gate.promise;
    return chat.send(id, body);
  });
  return gate;
}

async function type(text: string) {
  await fireEvent.changeText(screen.getByTestId('chat-input'), text);
}

/** Soxta taymerlar bilan vaqtni oldinga surish (`jest.useFakeTimers()` dan keyin). */
const advance = async (ms: number) => {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
};

beforeEach(() => {
  useSettings.setState({ uiLang: 'uz' });
});

afterEach(() => {
  jest.useRealTimers();
});

describe('Meeting chat tab', () => {
  it("shows this recording's conversation oldest first: names instead of [S#], citations seek the player, follow-ups only under the latest answer", async () => {
    const { api } = await openChat();
    await waitFor(() => expect(screen.getByTestId(`chat-turn-${T2.id}`)).toBeTruthy());
    expect(api.chatHistory).toHaveBeenCalledWith(ID);
    const json = JSON.stringify(screen.toJSON());
    expect(json.indexOf(`chat-turn-${T1.id}`)).toBeLessThan(json.indexOf(`chat-turn-${T2.id}`));

    const first = within(screen.getByTestId(`chat-turn-${T1.id}`));
    expect(first.getByText('Kim hisobot yuboradi?')).toBeTruthy();
    expect(first.getByText('2-ishtirokchi ertaga yuboradi.')).toBeTruthy();
    expect(first.getByText('2-ishtirokchi: Men ertaga hisobotni yuboraman.')).toBeTruthy();
    // Takliflar - faqat oxirgi javob ostida.
    expect(first.queryByText('Qachon?')).toBeNull();

    const last = within(screen.getByTestId(`chat-turn-${T2.id}`));
    expect(last.getByText('PDF hisobotni Aziz tekshiradi.')).toBeTruthy();
    expect(last.getByText("Aziz: Bugun narxlarni ko'ramiz.")).toBeTruthy();
    for (const f of T2.followUps) expect(last.getByText(f)).toBeTruthy();

    // Manba chipi pleerni o'sha joyga o'tkazadi.
    await fireEvent.press(last.getByTestId('ev-4.3'));
    await waitFor(() => expect(player.seekTo).toHaveBeenCalledWith(4.3));

    // Tepada: kim javob beradi va "Yangi suhbat"; bo'sh holat yo'q.
    expect(screen.getByText('Javob beradi: Claude Sonnet 5.5')).toBeTruthy();
    expect(screen.getByTestId('chat-reset')).toHaveTextContent('Yangi suhbat');
    expect(screen.queryByTestId('chat-empty')).toBeNull();
  });

  it('send is optimistic: the question shows at once with "Barno yozmoqda…", no second send while waiting, then the server turn replaces it', async () => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    expect(screen.getByTestId('chat-send')).toBeDisabled(); // bo'sh maydon
    const gate = holdNextSend(api, chat);

    await type('  Muddat qachon?  ');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(within(await screen.findByTestId('chat-outgoing')).getByText('Muddat qachon?')).toBeTruthy();
    expect(screen.getByTestId('chat-typing')).toHaveTextContent('Barno yozmoqda…');
    expect(screen.getByTestId('chat-input').props.value).toBe('');
    expect(api.sendChat).toHaveBeenCalledWith(ID, { message: 'Muddat qachon?', language: 'uz', channel: 'mobile', clientId: KEY });

    // Javob kutilayotganda: takliflar yo'q, "Yangi suhbat" o'chiq, yangi matn yuborilmaydi (lekin saqlanadi).
    expect(screen.queryByText('Muddat?')).toBeNull();
    expect(screen.getByTestId('chat-reset')).toBeDisabled();
    await type('Kim tasdiqlaydi?');
    expect(screen.getByTestId('chat-send')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(api.sendChat).toHaveBeenCalledTimes(1);

    await act(async () => gate.release());
    const turn = within(await screen.findByTestId(`chat-turn-${turnId(1)}`));
    expect(turn.getByText('Muddat qachon?')).toBeTruthy();
    expect(turn.getByText('2-ishtirokchi javobi: Muddat qachon?')).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-typing')).toBeNull());
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    // Takliflar endi yangi (oxirgi) javob ostida.
    expect(turn.getByText('Taklif 1a')).toBeTruthy();
    expect(screen.queryByText('Muddat?')).toBeNull();
    // Kutib turgan matn qoldi - endi yuboriladi (yangi xabar - yangi kalit).
    expect(screen.getByTestId('chat-input').props.value).toBe('Kim tasdiqlaydi?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    await screen.findByTestId(`chat-turn-${turnId(2)}`);
    expect(api.sendChat).toHaveBeenCalledTimes(2);
    expect(sentKeys(api)).toEqual([KEY, KEY]);
    expect(new Set(sentKeys(api)).size).toBe(2);
  });

  it('the composer caps a message at 1000 characters and shows a counter only near the limit', async () => {
    const { api } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    expect(screen.getByTestId('chat-input').props.maxLength).toBe(1000);
    await type('x'.repeat(899));
    expect(screen.queryByText('899/1000')).toBeNull();
    await type('x'.repeat(950));
    expect(screen.getByText('950/1000')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('chat-send'));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledWith(ID, { message: 'x'.repeat(950), language: 'uz', channel: 'mobile', clientId: KEY }));
    expect(screen.queryByText('950/1000')).toBeNull();
  });

  it('a failed message stays with the reason and "Qayta yuborish" resends the same text with the SAME key', async () => {
    const { api, chat } = await openChat();
    // Ikki marta xato, uchinchisi - xotiradagi serverdan oddiy javob.
    api.sendChat
      .mockRejectedValueOnce(new ApiError(503, 'llm_unavailable', "Model hozir javob bera olmayapti - keyinroq urinib ko'ring"))
      .mockRejectedValueOnce(new ApiError(429, 'rate_limited', "So'rovlar ko'p", null, 60));
    await screen.findByTestId(`chat-turn-${T2.id}`);
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    const error = within(await screen.findByTestId('chat-error'));
    expect(error.getByText("AI hozir mavjud emas - keyinroq urinib ko'ring")).toBeTruthy();
    expect(error.getByTestId('chat-retry')).toHaveTextContent('Qayta yuborish');
    expect(screen.getByTestId('chat-outgoing')).toHaveTextContent('Narx qancha?');
    expect(screen.queryByTestId('chat-typing')).toBeNull();

    await fireEvent.press(screen.getByTestId('chat-retry'));
    expect(await screen.findByText("Juda ko'p so'rov - birozdan keyin urinib ko'ring")).toBeTruthy();
    expect(screen.queryByText("AI hozir mavjud emas - keyinroq urinib ko'ring")).toBeNull();
    expect(screen.getByTestId('chat-outgoing')).toHaveTextContent('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-retry'));
    expect(within(await screen.findByTestId(`chat-turn-${turnId(1)}`)).getByText('2-ishtirokchi javobi: Narx qancha?')).toBeTruthy();
    expect(screen.queryByTestId('chat-error')).toBeNull();
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(api.sendChat.mock.calls.map((c) => c[1].message)).toEqual(['Narx qancha?', 'Narx qancha?', 'Narx qancha?']);
    // Uchala urinish - bitta xabar: kalit o'zgarmaydi (server ikkinchi savol-javob yaratmaydi).
    const [first] = sentKeys(api);
    expect(first).toEqual(KEY);
    expect(sentKeys(api)).toEqual([first, first, first]);
    expect(chat.history(ID).items.filter((x) => x.question === 'Narx qancha?')).toHaveLength(1);
  });

  it.each([
    ['the connection dropped', new ApiError(0, 'network', 'Tarmoq xatosi')],
    ['the proxy gave up (HTML 504)', new ApiError(504, 'gateway_timeout', 'Request failed (504)', null)],
    ['the phone stopped waiting (AI_TIMEOUT_MS)', new ApiError(0, 'timeout', "So'rov vaqti tugadi (150 s)")],
  ])('%s but the server stored the turn: after the refetch it shows exactly once - no failed copy, no "Qayta yuborish"', async (_why, lost) => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockImplementationOnce(async (id: string, body: ChatRequest) => {
      chat.send(id, body); // server javob yozdi va saqladi...
      throw lost; // ...javob esa telefonga yetmadi
    });
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));

    const turn = within(await screen.findByTestId(`chat-turn-${turnId(1)}`));
    expect(turn.getByText('2-ishtirokchi javobi: Narx qancha?')).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-error')).toBeNull());
    expect(screen.queryByTestId('chat-retry')).toBeNull();
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(screen.getAllByText('Narx qancha?')).toHaveLength(1);
    // Chat odatdagi holatda: takliflar shu (oxirgi) javob ostida.
    expect(turn.getByText('Taklif 1a')).toBeTruthy();
    expect(api.sendChat).toHaveBeenCalledTimes(1);
    expect(chat.history(ID).items.filter((x) => x.question === 'Narx qancha?')).toHaveLength(1);
  });

  it('the server finishes after the phone gave up: the failed copy shows until the next history load brings the turn, then it is gone for good', async () => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockRejectedValueOnce(new ApiError(504, 'gateway_timeout', 'Request failed (504)', null));
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    // Hali hech narsa ma'lum emas - xato va "Qayta yuborish" ko'rinadi.
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    chat.send(ID, { message: 'Narx qancha?', channel: 'mobile', clientId: sentKeys(api)[0] }); // server keyinroq tugatdi

    await fireEvent.press(screen.getByTestId('tab-transcript'));
    await fireEvent.press(screen.getByTestId('tab-chat'));
    await screen.findByTestId(`chat-turn-${turnId(1)}`);
    await waitFor(() => expect(screen.queryByTestId('chat-error')).toBeNull());
    expect(screen.getAllByText('Narx qancha?')).toHaveLength(1);

    // Telegram'da "Yangi suhbat" bosildi (ilova bilmaydi): savol-javob ro'yxatdan chiqadi - xato qaytmaydi.
    chat.reset(ID);
    await fireEvent.press(screen.getByTestId('tab-summary'));
    await fireEvent.press(screen.getByTestId('tab-chat'));
    expect(await screen.findByTestId('chat-empty')).toBeTruthy();
    expect(screen.queryByTestId('chat-error')).toBeNull();
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(api.sendChat).toHaveBeenCalledTimes(1);
  });

  it('the server stores the answer only after the proxy gave up (504): about 8 s later the history is read once more and the turn shows by itself - one turn, no error, nothing resent', async () => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockRejectedValueOnce(new ApiError(504, 'gateway_timeout', 'Request failed (504)', null));
    jest.useFakeTimers();
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    // Xatodan keyingi darhol qayta o'qish tugadi - server hali yozmoqda, savol-javob yo'q.
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('chat-error')).toBeTruthy();
    // Server javobni proksi to'xtagandan bir necha soniya keyin tugatib saqladi - o'sha kalit bilan.
    chat.send(ID, { message: 'Narx qancha?', channel: 'mobile', clientId: sentKeys(api)[0] });

    await advance(CHAT_RECHECK_MS);
    const turn = within(await screen.findByTestId(`chat-turn-${turnId(1)}`));
    expect(turn.getByText('2-ishtirokchi javobi: Narx qancha?')).toBeTruthy();
    expect(screen.queryByTestId('chat-error')).toBeNull();
    expect(screen.queryByTestId('chat-retry')).toBeNull();
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(screen.getAllByText('Narx qancha?')).toHaveLength(1);
    expect(api.chatHistory).toHaveBeenCalledTimes(3);
    expect(api.sendChat).toHaveBeenCalledTimes(1);
    // Faqat bir marta: keyin tarix o'z-o'zidan qayta o'qilmaydi.
    await advance(5 * CHAT_RECHECK_MS);
    expect(api.chatHistory).toHaveBeenCalledTimes(3);
  });

  it('a definite failure from our own server (503 llm_unavailable envelope) is not re-checked later - nothing was stored, "Qayta yuborish" stays', async () => {
    const { api } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockRejectedValueOnce(new ApiError(503, 'llm_unavailable', 'x', { code: 'llm_unavailable' }));
    jest.useFakeTimers();
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(2));
    await advance(3 * CHAT_RECHECK_MS);
    expect(api.chatHistory).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('chat-retry')).toBeTruthy();
  });

  it('"Qayta yuborish" after the server stored the answer late: the same key brings back that turn - no duplicate', async () => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockRejectedValueOnce(new ApiError(504, 'gateway_timeout', 'Request failed (504)', null));
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(2));
    chat.send(ID, { message: 'Narx qancha?', channel: 'mobile', clientId: sentKeys(api)[0] }); // server keyinroq saqladi

    await fireEvent.press(screen.getByTestId('chat-retry'));
    expect(await screen.findByTestId(`chat-turn-${turnId(1)}`)).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-outgoing')).toBeNull());
    const [first, again] = sentKeys(api);
    expect(again).toBe(first);
    expect(chat.history(ID).items.filter((x) => x.question === 'Narx qancha?')).toHaveLength(1);
    expect(screen.getAllByText('Narx qancha?')).toHaveLength(1);
    expect(screen.queryByTestId('chat-error')).toBeNull();
  });

  it('"Qayta yuborish" while the history read after the error is still on its way: the server dedupes the same key - one turn, no failed copy', async () => {
    const slow = deferred();
    let reads = 0;
    const { api, chat } = await openChat({
      over: (c) => ({
        chatHistory: jest.fn(async (id: string) => {
          reads += 1;
          if (reads === 2) await slow.promise; // xatodan keyingi qayta o'qish sekin (yomon tarmoq)
          return c.history(id);
        }),
      }),
    });
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockImplementationOnce(async (id: string, body: ChatRequest) => {
      chat.send(id, body); // server saqladi...
      throw new ApiError(0, 'network', 'Tarmoq xatosi'); // ...javob telefonga yetmadi
    });
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    expect(reads).toBe(2); // qayta o'qish boshlangan, tugamagan

    await fireEvent.press(screen.getByTestId('chat-retry'));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(2));
    await act(async () => slow.release());
    expect(await screen.findByTestId(`chat-turn-${turnId(1)}`)).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-outgoing')).toBeNull());
    const [first, again] = sentKeys(api);
    expect(again).toBe(first);
    expect(chat.history(ID).items.filter((x) => x.question === 'Narx qancha?')).toHaveLength(1);
    expect(screen.getAllByText('Narx qancha?')).toHaveLength(1);
    expect(screen.queryByTestId('chat-error')).toBeNull();
  });

  it('a resend still waiting for its answer counts as delivered once the history brings the turn with its key: "Barno yozmoqda…" goes, the late answer changes nothing', async () => {
    const slow = deferred();
    let reads = 0;
    const { api, chat } = await openChat({
      over: (c) => ({
        chatHistory: jest.fn(async (id: string) => {
          reads += 1;
          if (reads === 2) await slow.promise;
          return c.history(id);
        }),
      }),
    });
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat.mockImplementationOnce(async (id: string, body: ChatRequest) => {
      chat.send(id, body);
      throw new ApiError(0, 'timeout', "So'rov vaqti tugadi (150 s)");
    });
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    // Qayta yuborish: server o'sha kalitli savol-javobni qaytaradi, lekin javob ham sekin keladi.
    const gate = holdNextSend(api, chat);
    await fireEvent.press(screen.getByTestId('chat-retry'));
    expect(await screen.findByTestId('chat-typing')).toBeTruthy();

    // Sekin qayta o'qish keldi: tarixda shu kalitli savol-javob - xabar yetib borgan.
    await act(async () => slow.release());
    expect(await screen.findByTestId(`chat-turn-${turnId(1)}`)).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-typing')).toBeNull());
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(screen.getByTestId('chat-send')).toBeTruthy();

    await act(async () => gate.release());
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(3));
    expect(screen.getAllByText('Narx qancha?')).toHaveLength(1);
    expect(screen.queryByTestId('chat-typing')).toBeNull();
    expect(screen.queryByTestId('chat-error')).toBeNull();
    expect(chat.history(ID).items.filter((x) => x.question === 'Narx qancha?')).toHaveLength(1);
  });

  it('"Yangi suhbat" while a delivered resend is still on its way: its late answer does not bring the archived turn back into the new conversation', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    const slow = deferred();
    const stalled = deferred();
    let reads = 0;
    let stall = false;
    const { api, chat } = await openChat({
      seed: [T1],
      over: (c) => ({
        chatHistory: jest.fn(async (id: string) => {
          reads += 1;
          if (reads === 2) await slow.promise;
          // Tarmoq yomon: kech javobdan keyingi o'qish osilib turadi - ekranda faqat `onSuccess` yozgani qoladi.
          if (stall) await stalled.promise;
          return c.history(id);
        }),
      }),
    });
    await screen.findByTestId(`chat-turn-${T1.id}`);
    // Server saqladi, javob yo'lda yo'qoldi (noaniq xato).
    api.sendChat.mockImplementationOnce(async (id: string, body: ChatRequest) => {
      chat.send(id, body);
      throw new ApiError(0, 'network', 'Tarmoq xatosi');
    });
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-retry')).toBeTruthy();
    // "Qayta yuborish" (o'sha kalit): server darhol o'sha savol-javobni qaytaradi, lekin javob sekin keladi.
    const gate = deferred();
    api.sendChat.mockImplementationOnce(async (id: string, body: ChatRequest) => {
      const turn = chat.send(id, body);
      await gate.promise;
      return turn;
    });
    await fireEvent.press(screen.getByTestId('chat-retry'));
    expect(await screen.findByTestId('chat-typing')).toBeTruthy();
    // Sekin o'qish shu kalitli savol-javobni olib keldi - xabar yetib borgan, kutish yo'qoldi.
    await act(async () => slow.release());
    await screen.findByTestId(`chat-turn-${turnId(1)}`);
    await waitFor(() => expect(screen.queryByTestId('chat-typing')).toBeNull());
    // "Yangi suhbat": server hammasini arxivlaydi.
    await fireEvent.press(screen.getByTestId('chat-reset'));
    const buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
    await act(async () => buttons.find((b) => b.text === 'Boshlash')?.onPress?.());
    expect(await screen.findByTestId('chat-empty')).toBeTruthy();
    // "Yangi suhbat"dan keyingi o'qish (3-chi) tugadi - endi ro'yxatda faqat yangi suhbat (bo'sh).
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(3));
    await act(async () => {
      await api.chatHistory.mock.results[2]?.value;
    });
    // Qayta yuborishning javobi endi keldi: `onSuccess` keshga yozadi (yoki yozmaydi), so'ng ro'yxatni qayta
    // o'qiydi (4-chi o'qish - osilib turadi).
    stall = true;
    await act(async () => gate.release());
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(4));
    // Kesh o'zgarishi ekranga keyingi taymer navbatida yetadi (React Query bildirishnomalari; `renderRouter`
    // soxta taymerlarni yoqadi) - vaqtni oldinga surib kutamiz.
    await advance(50);
    // Eski suhbatning javobi yangi suhbatga qaytmadi.
    expect(screen.queryByTestId(`chat-turn-${turnId(1)}`)).toBeNull();
    expect(screen.getByTestId('chat-empty')).toBeTruthy();
    expect(chat.history(ID).items).toHaveLength(0);
    stalled.release();
    alert.mockRestore();
  });

  it('sent before the history arrived and really failed (503): an EARLIER identical question in the history does not hide the error', async () => {
    const earlier = chatTurn({ id: '3'.repeat(32), question: 'Narx qancha?', answer: 'Eski javob.', clientId: '0c9a7e51-2f4d-4b8e-9a61-3d2c1b0a9f87' });
    const loading = deferred();
    const { api } = await openChat({
      seed: [T1, earlier],
      over: (c) => ({
        chatHistory: jest.fn(async (id: string) => {
          await loading.promise;
          return c.history(id);
        }),
        sendChat: jest.fn().mockRejectedValue(new ApiError(503, 'llm_unavailable', 'x', { code: 'llm_unavailable' })),
      }),
    });
    // Tarix hali kelmagan - yozish maydoni bor, odam yuboradi.
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId('chat-error')).toBeTruthy();
    await act(async () => loading.release());
    await screen.findByTestId(`chat-turn-${earlier.id}`);
    // Haqiqiy 503 (hech narsa saqlanmagan) jim yutilmaydi: sababi va "Qayta yuborish" qoladi.
    expect(within(screen.getByTestId('chat-error')).getByText("AI hozir mavjud emas - keyinroq urinib ko'ring")).toBeTruthy();
    expect(screen.getByTestId('chat-retry')).toBeTruthy();
    expect(screen.getByTestId('chat-outgoing')).toHaveTextContent('Narx qancha?');
  });

  it('the same question asked earlier is not proof of delivery: a message that really failed keeps "Qayta yuborish"', async () => {
    const earlier = chatTurn({ id: '3'.repeat(32), question: 'Narx qancha?', answer: 'Eski javob.' });
    const { api } = await openChat({ seed: [T1, earlier] });
    await screen.findByTestId(`chat-turn-${earlier.id}`);
    api.sendChat.mockRejectedValueOnce(new ApiError(0, 'network', 'Tarmoq xatosi'));
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(within(await screen.findByTestId('chat-error')).getByText("Internet yo'q")).toBeTruthy();
    // Xatodan keyingi qayta o'qish ham tugadi - eski qator yuborishda ma'lum edi, bu xabarniki emas.
    await waitFor(() => expect(api.chatHistory).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('chat-retry')).toBeTruthy();
    expect(screen.getByTestId('chat-outgoing')).toHaveTextContent('Narx qancha?');

    await fireEvent.press(screen.getByTestId('chat-retry'));
    expect(within(await screen.findByTestId(`chat-turn-${turnId(1)}`)).getByText('2-ishtirokchi javobi: Narx qancha?')).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-outgoing')).toBeNull());
    expect(api.sendChat).toHaveBeenCalledTimes(2);
  });

  it('an older failed message does not resurface when a later one turns out to be delivered', async () => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    api.sendChat
      .mockRejectedValueOnce(new ApiError(503, 'llm_unavailable', 'x')) // haqiqatan yetib bormadi
      .mockImplementationOnce(async (id: string, body: ChatRequest) => {
        chat.send(id, body);
        throw new ApiError(0, 'network', 'Tarmoq xatosi');
      });
    await type('Birinchi savol');
    await fireEvent.press(screen.getByTestId('chat-send'));
    await screen.findByTestId('chat-error');
    await type('Ikkinchi savol');
    await fireEvent.press(screen.getByTestId('chat-send'));

    await screen.findByTestId(`chat-turn-${turnId(1)}`);
    await waitFor(() => expect(screen.queryByTestId('chat-error')).toBeNull());
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(screen.queryByText('Birinchi savol')).toBeNull();
    expect(screen.getAllByText('Ikkinchi savol')).toHaveLength(1);

    // Ikkala xato ham mutatsiya keshidan ketgan: ro'yxat boshqa kanalda tozalansa ham birinchisi
    // "oxirgi xabar" bo'lib qaytmaydi - bo'sh holat ko'rinadi.
    chat.reset(ID);
    await fireEvent.press(screen.getByTestId('tab-summary'));
    await fireEvent.press(screen.getByTestId('tab-chat'));
    expect(await screen.findByTestId('chat-empty')).toBeTruthy();
    expect(screen.queryByTestId('chat-error')).toBeNull();
    expect(screen.queryByText('Birinchi savol')).toBeNull();
  });

  it('an HTML 403 from the edge (WAF) is not "no permission": the message did not get through', async () => {
    await openChat({ over: { sendChat: jest.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'Request failed (403)', null)) } });
    await screen.findByTestId(`chat-turn-${T2.id}`);
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    const error = within(await screen.findByTestId('chat-error'));
    expect(error.getByText('Xabar yetib bormadi - qayta yuboring')).toBeTruthy();
    expect(error.getByTestId('chat-retry')).toHaveTextContent('Qayta yuborish');
    expect(screen.queryByText(/Ruxsat|ruxsat yo'q|<html|403/)).toBeNull();
  });

  it('"Yangi suhbat" asks first; confirming archives the turns on the server and starts fresh', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    try {
      const { api, chat } = await openChat();
      await screen.findByTestId(`chat-turn-${T2.id}`);
      await fireEvent.press(screen.getByTestId('chat-reset'));
      expect(alert.mock.calls.at(-1)?.slice(0, 2)).toEqual([
        'Yangi suhbat',
        "Oldingi savol-javoblar ro'yxatdan olinadi va Barno ularni endi hisobga olmaydi. Davom etasizmi?",
      ]);
      let buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => buttons.find((b) => b.text === 'Bekor qilish')?.onPress?.());
      expect(api.resetChat).not.toHaveBeenCalled();
      expect(screen.getByTestId(`chat-turn-${T1.id}`)).toBeTruthy();

      await fireEvent.press(screen.getByTestId('chat-reset'));
      buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => buttons.find((b) => b.text === 'Boshlash')?.onPress?.());
      await waitFor(() => expect(api.resetChat).toHaveBeenCalledWith(ID));
      expect(await screen.findByTestId('chat-empty')).toBeTruthy();
      expect(screen.queryByTestId(`chat-turn-${T1.id}`)).toBeNull();
      expect(screen.queryByTestId('chat-reset')).toBeNull();
      // Serverda o'chirilmagan - arxivda.
      expect(chat.archived.map((x) => x.id)).toEqual([T1.id, T2.id]);
    } finally {
      alert.mockRestore();
    }
  });

  it('a failed message of the old conversation is gone after "Yangi suhbat"', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    try {
      const { api } = await openChat();
      api.sendChat.mockRejectedValueOnce(new ApiError(503, 'llm_unavailable', 'x'));
      await screen.findByTestId(`chat-turn-${T2.id}`);
      await type('Narx qancha?');
      await fireEvent.press(screen.getByTestId('chat-send'));
      await screen.findByTestId('chat-error');
      await fireEvent.press(screen.getByTestId('chat-reset'));
      const buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => buttons.find((b) => b.text === 'Boshlash')?.onPress?.());
      expect(await screen.findByTestId('chat-empty')).toBeTruthy();
      expect(screen.queryByTestId('chat-error')).toBeNull();
      expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    } finally {
      alert.mockRestore();
    }
  });

  it('the waiting message belongs to its own recording only (query and mutation keys are per meeting)', async () => {
    const A = 'a'.repeat(32);
    const B = 'b'.repeat(32);
    const qc = new QueryClient({ defaultOptions: { mutations: { gcTime: Infinity } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    // A yozuvga yuborilgan, javobi hali kelmagan xabar.
    void qc.getMutationCache().build(qc, { mutationKey: chatSendKey(A), mutationFn: () => new Promise<never>(() => {}) }).execute({ message: 'A savoli' });
    const a = await renderHook(() => useChatOutgoing(A, undefined), { wrapper });
    const b = await renderHook(() => useChatOutgoing(B, undefined), { wrapper });
    expect(a.result.current).toMatchObject({ status: 'pending', message: 'A savoli' });
    expect(b.result.current).toBeNull();
    expect([isChatSending(qc, A), isChatSending(qc, B)]).toEqual([true, false]);
  });

  it('a delivered failed send leaves the mutation cache together with older failures, so neither can come back', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false, gcTime: Infinity } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    const cache = qc.getMutationCache();
    const failSend = (message: string, clientId: string) =>
      cache
        .build(qc, { mutationKey: chatSendKey(ID), mutationFn: async () => Promise.reject(new ApiError(0, 'network', 'Tarmoq xatosi')) })
        .execute({ message, clientId })
        .catch(() => undefined);
    await failSend('Birinchi savol', 'kalit-birinchi-00000'); // haqiqatan yetib bormagan
    await failSend('Ikkinchi savol', 'kalit-ikkinchi-00000'); // server saqlagan, javob yo'lda yo'qolgan
    const stored = chatTurn({ id: turnId(1), question: 'Ikkinchi savol', clientId: 'kalit-ikkinchi-00000' });

    const hook = await renderHook(({ items }: { items: ChatTurn[] }) => useChatOutgoing(ID, items), { wrapper, initialProps: { items: [T1] } });
    expect(hook.result.current).toMatchObject({ status: 'error', message: 'Ikkinchi savol', clientId: 'kalit-ikkinchi-00000' });
    // Savol matni bir xil bo'lsa ham boshqa kalitli qator - yetib borgani emas.
    await hook.rerender({ items: [T1, chatTurn({ id: turnId(9), question: 'Ikkinchi savol', clientId: 'boshqa-kalit-0000000' })] });
    expect(hook.result.current).toMatchObject({ status: 'error', message: 'Ikkinchi savol' });
    await hook.rerender({ items: [T1, stored] });
    expect(hook.result.current).toBeNull();
    await waitFor(() => expect(cache.findAll({ mutationKey: chatSendKey(ID) })).toHaveLength(0));
    // Savol-javob tarixdan chiqsa ham (boshqa kanalda "Yangi suhbat") - xato qaytmaydi, eskisi ham chiqmaydi.
    await hook.rerender({ items: [] });
    expect(hook.result.current).toBeNull();
  });

  it('a send still on its way whose turn already came with the history: hidden at once and out of the cache (no longer "sending"); its late answer changes nothing', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false, gcTime: Infinity } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    const cache = qc.getMutationCache();
    const stored = chatTurn({ id: turnId(1), question: 'Narx qancha?', clientId: 'kalit-yolda-00000000' });
    const gate = deferred();
    const running = cache
      .build(qc, {
        mutationKey: chatSendKey(ID),
        mutationFn: async () => {
          await gate.promise;
          return stored;
        },
      })
      .execute({ message: 'Narx qancha?', clientId: 'kalit-yolda-00000000' });

    const hook = await renderHook(({ items }: { items: ChatTurn[] }) => useChatOutgoing(ID, items), { wrapper, initialProps: { items: [T1] } });
    expect(hook.result.current).toMatchObject({ status: 'pending', message: 'Narx qancha?', clientId: 'kalit-yolda-00000000' });
    expect(isChatSending(qc, ID)).toBe(true);
    await hook.rerender({ items: [T1, stored] });
    expect(hook.result.current).toBeNull();
    await waitFor(() => expect(cache.findAll({ mutationKey: chatSendKey(ID) })).toHaveLength(0));
    expect(isChatSending(qc, ID)).toBe(false);

    await act(async () => gate.release());
    await expect(running).resolves.toEqual(stored);
    expect(hook.result.current).toBeNull();
  });

  it('a follow-up chip under the latest answer sends that question', async () => {
    const { api } = await openChat();
    await fireEvent.press(await screen.findByText('Kim tasdiqlaydi?'));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledWith(ID, { message: 'Kim tasdiqlaydi?', language: 'uz', channel: 'mobile', clientId: KEY }));
    await screen.findByTestId(`chat-turn-${turnId(1)}`);
  });

  it('empty chat explains the scope and offers the quick questions; the answer language follows the app language', async () => {
    useSettings.setState({ uiLang: 'ru' });
    const { api } = await openChat({ seed: [] });
    const empty = await screen.findByTestId('chat-empty');
    expect(within(empty).getByText('Задайте вопрос по этой записи. Barno опирается только на текст и резюме этого аудио и помнит ход беседы.')).toBeTruthy();
    expect(screen.queryByTestId('chat-reset')).toBeNull();
    await fireEvent.press(within(empty).getByText('Решения'));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledWith(ID, { message: 'Какие решения были приняты?', language: 'ru', channel: 'mobile', clientId: KEY }));
    expect(await screen.findByTestId(`chat-turn-${turnId(1)}`)).toBeTruthy();
    expect(screen.queryByTestId('chat-empty')).toBeNull();
  });

  it('uz empty state text matches the product copy', async () => {
    await openChat({ seed: [] });
    const empty = within(await screen.findByTestId('chat-empty'));
    expect(empty.getByText("Bu yozuv bo'yicha savol bering. Barno faqat shu audio matni va xulosasiga tayanadi va suhbatni eslab qoladi.")).toBeTruthy();
    for (const chip of ['Vazifalar', 'Qarorlar', 'Kuzatuv xabari']) expect(empty.getByText(chip)).toBeTruthy();
  });

  it('leaving the tab while Barno is answering keeps the question and the typing line; still no second send', async () => {
    const { api, chat } = await openChat();
    await screen.findByTestId(`chat-turn-${T2.id}`);
    const gate = holdNextSend(api, chat);
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    await screen.findByTestId('chat-typing');

    await fireEvent.press(screen.getByTestId('tab-summary'));
    expect(screen.queryByTestId('chat-typing')).toBeNull();
    await fireEvent.press(screen.getByTestId('tab-chat'));
    expect(await screen.findByTestId('chat-typing')).toBeTruthy();
    expect(screen.getByTestId('chat-outgoing')).toHaveTextContent('Narx qancha?');
    expect(await screen.findByTestId(`chat-turn-${T2.id}`)).toBeTruthy();
    await type('Yana bir savol');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(api.sendChat).toHaveBeenCalledTimes(1);

    await act(async () => gate.release());
    expect(await screen.findByTestId(`chat-turn-${turnId(1)}`)).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('chat-typing')).toBeNull());
  });

  it('transcript not ready: the existing banner and no composer (history is not requested)', async () => {
    const { api } = await openChat({
      over: { get: jest.fn(async () => meeting({ status: 'transcribing', progress: 10, transcript: { ...meeting().transcript, available: false } })) },
    });
    expect(await screen.findByText("Savol berish uchun matn tayyor bo'lishi kerak")).toBeTruthy();
    expect(screen.queryByTestId('chat-input')).toBeNull();
    expect(api.chatHistory).not.toHaveBeenCalled();
  });

  it.each([
    ['no body (nginx page)', null],
    ['our envelope without a code (route not found)', routeMissing],
  ])('history 404 without a server code - %s: an old server without /chat says so and hides the composer, no retry', async (_why, body) => {
    await openChat({ over: { chatHistory: jest.fn().mockRejectedValue(new ApiError(404, 'not_found', 'Not Found', body)) } });
    expect(await screen.findByTestId('chat-not-on-server')).toHaveTextContent('Chat serverda hali yoqilmagan - server yangilangach ishlaydi');
    expect(screen.queryByTestId('chat-gone')).toBeNull();
    expect(screen.queryByTestId('chat-input')).toBeNull();
    expect(screen.queryByText('Qayta urinish')).toBeNull();
  });

  it('history 404 with the server code not_found (recording deleted or not yours) is not an "old server": "Yozuv topilmadi", no composer, no retry; the recording is re-read', async () => {
    const { api } = await openChat({ over: { chatHistory: jest.fn().mockRejectedValue(recordingGone()) } });
    expect(await screen.findByTestId('chat-gone')).toHaveTextContent('Yozuv topilmadi');
    expect(screen.queryByText('Chat serverda hali yoqilmagan - server yangilangach ishlaydi')).toBeNull();
    expect(screen.queryByText("Oldingi savol-javoblarni yuklab bo'lmadi")).toBeNull();
    expect(screen.queryByTestId('chat-input')).toBeNull();
    expect(screen.queryByTestId('chat-empty')).toBeNull();
    expect(screen.queryByText('Qayta urinish')).toBeNull();
    // Yozuv sahifasi bir marta qayta o'qiladi (o'chirilgani ro'yxatga ham yetsin); chat tarixi esa qayta so'ralmaydi.
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(api.chatHistory).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['the next message gets it', 'send'],
    ['the next history read gets it (tab opened again)', 'read'],
  ] as const)('recording deleted AFTER the history loaded (404 not_found) - %s: "Yozuv topilmadi", no composer, no "Qayta yuborish", the recording is re-read', async (_why, via) => {
    let deleted = false;
    // Xabar yo'lida tarixni qayta o'qish sekin: chatni xabarning O'Z 404 i yopishi kerak.
    const slowRead = deferred();
    const { api } = await openChat({
      over: (c) => ({
        chatHistory: jest.fn(async (id: string) => {
          if (!deleted) return c.history(id);
          if (via === 'send') await slowRead.promise;
          throw recordingGone();
        }),
        sendChat: jest.fn(async () => {
          throw recordingGone();
        }),
        get: jest.fn(async () => {
          if (deleted) throw recordingGone();
          return meeting();
        }),
      }),
    });
    await screen.findByTestId(`chat-turn-${T2.id}`);
    const loads = api.get.mock.calls.length;
    deleted = true; // boshqa qurilmada o'chirildi (yoki saqlash muddati tugadi)
    if (via === 'send') {
      await type('Narx qancha?');
      await fireEvent.press(screen.getByTestId('chat-send'));
    } else {
      await fireEvent.press(screen.getByTestId('tab-summary'));
      await fireEvent.press(screen.getByTestId('tab-chat'));
    }

    expect(await screen.findByTestId('chat-gone')).toHaveTextContent('Yozuv topilmadi');
    expect(screen.queryByTestId('chat-error')).toBeNull();
    expect(screen.queryByTestId('chat-retry')).toBeNull();
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(screen.queryByTestId('chat-input')).toBeNull();
    expect(screen.queryByTestId('chat-reset')).toBeNull();
    expect(screen.queryByTestId(`chat-turn-${T2.id}`)).toBeNull();
    expect(screen.queryByText('Qayta urinish')).toBeNull();
    await waitFor(() => expect(api.get.mock.calls.length).toBe(loads + 1));
    // Sekin o'qish ham o'sha 404 bilan keldi - holat o'zgarmaydi, yozuv qayta-qayta so'ralmaydi.
    await act(async () => slowRead.release());
    await waitFor(() => expect(screen.getByTestId('chat-gone')).toBeTruthy());
    expect(screen.queryByTestId('chat-input')).toBeNull();
    expect(api.get.mock.calls.length).toBe(loads + 1);
  });

  it('"Yangi suhbat" on a recording deleted meanwhile (404 not_found) closes the chat the same way', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    try {
      const { api } = await openChat({ over: { resetChat: jest.fn().mockRejectedValue(recordingGone()) } });
      await screen.findByTestId(`chat-turn-${T2.id}`);
      await fireEvent.press(screen.getByTestId('chat-reset'));
      const buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => buttons.find((b) => b.text === 'Boshlash')?.onPress?.());
      expect(await screen.findByTestId('chat-gone')).toHaveTextContent('Yozuv topilmadi');
      expect(screen.queryByTestId('chat-input')).toBeNull();
      expect(screen.queryByTestId('chat-reset')).toBeNull();
      await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    } finally {
      alert.mockRestore();
    }
  });

  it('recording gone while a message was on its way: no failed bubble with "Qayta yuborish" under the banner', async () => {
    const gone = recordingGone();
    const loading = deferred();
    const { api } = await openChat({
      over: {
        chatHistory: jest.fn(async () => {
          await loading.promise;
          throw gone;
        }),
        sendChat: jest.fn().mockRejectedValue(gone),
      },
    });
    // Tarix hali kelmagan - yozish maydoni bor, xabar yuboriladi va 404 oladi.
    await type('Narx qancha?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(1));
    await act(async () => loading.release());

    expect(await screen.findByTestId('chat-gone')).toHaveTextContent('Yozuv topilmadi');
    expect(screen.queryByTestId('chat-retry')).toBeNull();
    expect(screen.queryByTestId('chat-outgoing')).toBeNull();
    expect(screen.queryByTestId('chat-input')).toBeNull();
    expect(screen.queryByText('Qayta urinish')).toBeNull();
  });

  it('a failed history load can be retried and then shows the conversation', async () => {
    const chat = chatBackend({ [ID]: [T1] });
    const history = jest
      .fn()
      .mockRejectedValueOnce(new ApiError(0, 'network', 'Tarmoq xatosi'))
      .mockImplementation(async (id: string) => chat.history(id));
    await openChat({ over: { chatHistory: history } });
    expect(await screen.findByText("Oldingi savol-javoblarni yuklab bo'lmadi")).toBeTruthy();
    expect(screen.getByTestId('chat-input')).toBeTruthy();
    await fireEvent.press(screen.getByText('Qayta urinish'));
    expect(await screen.findByTestId(`chat-turn-${T1.id}`)).toBeTruthy();
    expect(screen.queryByText("Oldingi savol-javoblarni yuklab bo'lmadi")).toBeNull();
  });
});
