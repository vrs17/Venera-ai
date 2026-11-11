/**
 * React Query hook'lari (server holati). Polling qoidasi spec 3.2 #7:
 * server `pollAfterSec` beradi (3/10/5/600 s), `ready`/`failed` da null -
 * polling to'xtaydi.
 *
 * Mutatsiya xatolari: `_layout.tsx` dagi `MutationCache.onError` HAR BIRINI
 * toast bilan ko'rsatadi (kod -> i18n `err.<code>`). Xatoni o'zi ko'rsatadigan
 * mutatsiya `meta: { silentError: true }` beradi.
 */
import { useMutation, useMutationState, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import type {
  ActionItem,
  ChatHistory,
  ChatTurn,
  CreateActionItemRequest,
  CreateSummaryRequest,
  Lang,
  Meeting,
  MeetingOrigin,
  PatchActionItemRequest,
  PatchMeetingRequest,
  PatchSegmentRequest,
  Transcript,
} from '@/api/types';
import { useServices } from '@/services';

import { CHAT_RECHECK_MS, chatOutcomeUnknown, wasDelivered, withTurn } from './chatModel';

export const qk = {
  config: ['meetings', 'config'] as const,
  /** Plaud ro'yxati: qidiruv + manba filtri (`null` - hammasi). `['meetings', 'list']` prefiksi - hammasini yangilash. */
  list: (q: string, origin: MeetingOrigin | null) => ['meetings', 'list', q, origin ?? 'all'] as const,
  meeting: (id: string) => ['meetings', id] as const,
  transcript: (id: string) => ['meetings', id, 'transcript'] as const,
  summaries: (id: string) => ['meetings', id, 'summaries'] as const,
  summary: (id: string, sid: string) => ['meetings', id, 'summaries', sid] as const,
  actionItems: (id: string) => ['meetings', id, 'action-items'] as const,
  chat: (id: string) => ['meetings', id, 'chat'] as const,
  myItems: (status: string) => ['action-items', status] as const,
};

/** Chat xabari mutatsiyasining kaliti (mutatsiya keshida - so'rov kaliti `qk.chat` bilan aralashmaydi). */
export const chatSendKey = (id: string) => ['meetings', id, 'chat', 'send'] as const;

const PROCESSING = new Set(['uploaded', 'transcribing', 'summarizing', 'waiting_quota', 'uploading']);

export function isProcessing(m: Pick<Meeting, 'status' | 'summaryStatus'> | null | undefined): boolean {
  if (!m) return false;
  return PROCESSING.has(m.status) || m.summaryStatus === 'queued' || m.summaryStatus === 'running';
}

/** Server ko'rsatgan interval (ms) yoki false (to'xtash). */
export function pollInterval(m: Meeting | undefined): number | false {
  if (!m) return false;
  if (m.pollAfterSec != null) return Math.max(2, m.pollAfterSec) * 1000;
  // Server `uploading` paytida pollAfterSec=null beradi; yuklash tugashi bilan holat o'zgaradi.
  if (m.status === 'uploading') return 10_000;
  if (m.status === 'ready' && (m.summaryStatus === 'queued' || m.summaryStatus === 'running')) return 5000;
  return false;
}

export function useMeeting(id: string | null) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.meeting(id ?? ''),
    queryFn: () => meetings.get(id as string),
    enabled: !!id,
    refetchInterval: (q) => pollInterval(q.state.data),
  });
}

export function useTranscript(id: string | null, enabled = true) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.transcript(id ?? ''),
    queryFn: () => meetings.transcript(id as string),
    enabled: !!id && enabled,
  });
}

export function useSummaries(id: string | null, enabled = true, poll = false) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.summaries(id ?? ''),
    queryFn: () => meetings.summaries(id as string),
    enabled: !!id && enabled,
    refetchInterval: (q) =>
      poll || (q.state.data?.items ?? []).some((s) => s.status === 'queued' || s.status === 'running') ? 5000 : false,
  });
}

export function useSummary(id: string | null, summaryId: string | null) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.summary(id ?? '', summaryId ?? ''),
    queryFn: () => meetings.summary(id as string, summaryId as string),
    enabled: !!id && !!summaryId,
    refetchInterval: (q) => (q.state.data && (q.state.data.status === 'queued' || q.state.data.status === 'running') ? 5000 : false),
  });
}

export function useActionItems(id: string | null, enabled = true) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.actionItems(id ?? ''),
    queryFn: () => meetings.actionItems(id as string),
    enabled: !!id && enabled,
  });
}

/** Yozuv chati: faol savol-javoblar eskidan yangiga (`ChatView`). */
export function useChatHistory(id: string | null, enabled = true) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.chat(id ?? ''),
    queryFn: () => meetings.chatHistory(id as string),
    enabled: !!id && enabled,
  });
}

/** Chatga yuboriladigan xabar (kanal `mobile` - hook o'zi qo'shadi). */
export interface ChatSend {
  message: string;
  language?: Lang;
  /**
   * Idempotentlik kaliti (`newChatClientId`): yangi xabar - yangi kalit, "Qayta yuborish" - O'SHA kalit
   * (server shu kalitli savol-javobni qaytaradi, ikkinchisini yaratmaydi). Tarixda shu kalitli
   * savol-javob paydo bo'lsa xabar yetib borgan (`useChatOutgoing`).
   */
  clientId: string;
}

/**
 * Shu yozuvda "Yangi suhbat" necha marta muvaffaqiyatli bosilgani (ilova ishlab turgan davrda). Yuborish
 * boshida olinadi: javob kelguncha suhbat tozalangan bo'lsa (masalan yetib borgan "Qayta yuborish"
 * keshdan o'chib, so'rovi hali yo'lda edi), eski suhbatning javobi yangi suhbat ro'yxatiga yozilmaydi -
 * server uni allaqachon arxivlagan.
 */
const chatEpochs = new Map<string, number>();
const chatEpoch = (id: string) => chatEpochs.get(id) ?? 0;

export function useChatMutations(id: string) {
  const { meetings } = useServices();
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: qk.chat(id) });
  return {
    send: useMutation({
      mutationKey: chatSendKey(id),
      // Xato javob joyida ("Qayta yuborish" bilan) ko'rsatiladi - global toast kerak emas.
      meta: { silentError: true },
      mutationFn: (p: ChatSend) =>
        meetings.sendChat(id, { message: p.message, language: p.language, channel: 'mobile', clientId: p.clientId }),
      onMutate: () => ({ epoch: chatEpoch(id) }),
      // Mutatsiya darajasidagi qayta chaqiruvlar: tab almashib chat yopilgan bo'lsa ham javob keshga
      // yoziladi (javob kutilayotganda "Yangi suhbat" bo'lmagan bo'lsa). Keyin server ro'yxati qayta
      // o'qiladi (boshqa kanaldan berilgan savollar ham keladi).
      onSuccess: (turn, _p, ctx) => {
        if (ctx?.epoch === chatEpoch(id)) qc.setQueryData<ChatHistory>(qk.chat(id), (old) => withTurn(old, turn));
        refresh();
      },
      // Javob yo'lda yo'qolgan bo'lsa ham server uni saqlagan bo'lishi mumkin - ro'yxat haqiqatga tenglashadi.
      onError: refresh,
    }),
    reset: useMutation({
      mutationFn: () => meetings.resetChat(id),
      onSuccess: () => {
        chatEpochs.set(id, chatEpoch(id) + 1);
        qc.setQueryData<ChatHistory>(qk.chat(id), (old) => (old ? { ...old, items: [] } : old));
        forgetFailedSends(qc, id);
        refresh();
      },
    }),
  };
}

/** Chatda ko'rinadigan, hali tarixga kirmagan xabar: javob kutilmoqda yoki xato bilan tugagan. */
export interface ChatOutgoing {
  message: string;
  /** Xabarning kaliti: "Qayta yuborish" aynan shu kalit bilan yuboradi (bo'sh bo'lsa - yangi kalit oladi). */
  clientId: string;
  status: 'pending' | 'error';
  error: unknown;
}

/**
 * Shu yozuvga yuborilgan OXIRGI xabar - javob kutilayotgan yoki xato bilan tugagan bo'lsa (aks holda
 * `null`). Holat global mutatsiya keshidan o'qiladi: tab almashsa yoki sahifa qayta ochilsa ham
 * yuborilgan savol va "Barno yozmoqda…" yo'qolmaydi. Yangi xabar yoki "Qayta yuborish" - yangi
 * mutatsiya, eski xato o'z-o'zidan ko'rinmay qoladi.
 *
 * `items` - hozirgi tarix. Unda shu xabarning `clientId` li savol-javobi bo'lsa (`wasDelivered`: server
 * saqlagan, javob yo'lda yo'qolgan yoki hali yo'lda) - xabar yetib borgan: na xato, na "Barno
 * yozmoqda…" ko'rsatiladi va shu kalitli mutatsiyalar keshdan o'chadi - keyin tarixdan chiqsa ham
 * (masalan Telegram'da "Yangi suhbat") qaytib chiqmaydi.
 *
 * Javobi noma'lum xatodan (`chatOutcomeUnknown`: tarmoq, proksi 5xx) keyin tarix `CHAT_RECHECK_MS` dan
 * so'ng YANA bir marta o'qiladi - server kechroq saqlagan savol-javob odatda o'zi ko'rinadi. Taymer
 * chat ochiq turganda ishlaydi (yopilsa - bekor; qayta ochilganda tarix baribir o'qiladi).
 */
export function useChatOutgoing(id: string, items: readonly ChatTurn[] | undefined): ChatOutgoing | null {
  const qc = useQueryClient();
  const sends = useMutationState({
    filters: { mutationKey: chatSendKey(id) },
    select: (m) => ({ status: m.state.status, sent: m.state.variables as ChatSend | undefined, error: m.state.error as unknown }),
  });
  const last = sends[sends.length - 1];
  const clientId = last?.sent?.clientId ?? '';
  const open = last?.status === 'pending' || last?.status === 'error';
  const delivered = open && wasDelivered(items, clientId);
  // Shu urinishning xato obyekti (har urinishda yangi): kech tekshiruv har noma'lum xatoga bir marta.
  const unsure = last?.status === 'error' && !delivered && chatOutcomeUnknown(last.error) ? last.error : null;
  useEffect(() => {
    if (delivered) forgetDelivered(qc, id, clientId);
  }, [delivered, clientId, qc, id]);
  useEffect(() => {
    if (!unsure) return;
    const timer = setTimeout(() => void qc.invalidateQueries({ queryKey: qk.chat(id) }), CHAT_RECHECK_MS);
    return () => clearTimeout(timer);
  }, [unsure, qc, id]);
  if (!last || delivered || (last.status !== 'pending' && last.status !== 'error')) return null;
  return { status: last.status, message: last.sent?.message ?? '', clientId, error: last.error };
}

/** Javob kutilyaptimi - SINXRON, keshdan: ikki marta tez bosish ikkita so'rov yubormasin. */
export function isChatSending(qc: QueryClient, id: string): boolean {
  return qc.isMutating({ mutationKey: chatSendKey(id) }) > 0;
}

/**
 * Shu yozuvning xato bilan tugagan xabarlari mutatsiya keshidan o'chadi: "Yangi suhbat"dan keyin
 * eski suhbatniki ko'rinmasin.
 */
function forgetFailedSends(qc: QueryClient, id: string) {
  const cache = qc.getMutationCache();
  for (const m of cache.findAll({ mutationKey: chatSendKey(id), status: 'error' })) cache.remove(m);
}

/**
 * Yetib borgan xabar (`useChatOutgoing`) mutatsiya keshidan o'chadi: shu kalitli urinishlarning
 * hammasi - yo'ldagisi ham (so'rov baribir tugaydi, `onSuccess` javobni tarixga O'Z joyiga yozadi) -
 * va undan oldingi xatolar (ular baribir ko'rinmas edi: bittasi o'chsa, eskisi "oxirgi" bo'lib
 * qolib, qayta chiqmasin).
 */
function forgetDelivered(qc: QueryClient, id: string, clientId: string) {
  const cache = qc.getMutationCache();
  for (const m of cache.findAll({ mutationKey: chatSendKey(id) })) {
    if (m.state.status === 'error' || (m.state.variables as ChatSend | undefined)?.clientId === clientId) cache.remove(m);
  }
}

/**
 * Chat so'rovi `not_found` kodli 404 oldi (`chatRecordingGone`): yozuv o'chirilgan yoki begona. Yozuv
 * so'rovi va ro'yxat qayta o'qiladi - o'chirilgani boshqa joylarda ham ko'rinsin. Chat tarixi bu yerda
 * qayta so'ralmaydi (`exact`): o'sha 404 ni yana olardi. Har ochilishda bir marta.
 */
export function useMeetingGone(id: string, gone: boolean) {
  const qc = useQueryClient();
  const told = useRef(false);
  useEffect(() => {
    if (!gone || told.current) return;
    told.current = true;
    void qc.invalidateQueries({ queryKey: qk.meeting(id), exact: true });
    void qc.invalidateQueries({ queryKey: ['meetings', 'list'] });
  }, [gone, qc, id]);
}

function invalidateMeeting(qc: QueryClient, id: string) {
  void qc.invalidateQueries({ queryKey: ['meetings', id] });
  void qc.invalidateQueries({ queryKey: ['meetings', 'list'] });
}

export function useMeetingMutations(id: string) {
  const { meetings } = useServices();
  const qc = useQueryClient();
  const done = () => invalidateMeeting(qc, id);
  const setTranscript = (fn: (t: Transcript) => Transcript) =>
    qc.setQueryData<Transcript>(qk.transcript(id), (old) => (old ? fn(old) : old));

  return {
    patch: useMutation({ mutationFn: (b: PatchMeetingRequest) => meetings.patch(id, b), onSuccess: (m) => qc.setQueryData(qk.meeting(id), m) }),
    remove: useMutation({ mutationFn: () => meetings.remove(id), onSuccess: () => void qc.invalidateQueries({ queryKey: ['meetings'] }) }),
    retry: useMutation({ mutationFn: () => meetings.retry(id), onSuccess: done }),
    retranscribe: useMutation({
      mutationFn: (p: { language: Lang; expectedSpeakers?: number | null }) =>
        meetings.retranscribe(id, { language: p.language, expectedSpeakers: p.expectedSpeakers ?? null, confirmCharge: true }),
      onSuccess: done,
    }),
    renameSpeaker: useMutation({
      mutationFn: (p: { speakerId: string; name: string | null }) => meetings.renameSpeaker(id, p.speakerId, p.name),
      onSuccess: (r) => {
        setTranscript((t) => ({ ...t, speakers: r.speakers }));
        done();
      },
    }),
    mergeSpeakers: useMutation({
      mutationFn: (p: { from: string[]; into: string }) => meetings.mergeSpeakers(id, p),
      onSuccess: done,
    }),
    patchSegment: useMutation({
      mutationFn: (p: { segmentId: number; body: PatchSegmentRequest }) => meetings.patchSegment(id, p.segmentId, p.body),
      onSuccess: (r) => {
        setTranscript((t) => ({
          ...t,
          transcriptRev: r.transcriptRev,
          segments: t.segments.map((s) => (s.id === r.segment.id ? r.segment : s)),
        }));
        done();
      },
    }),
    createSummary: useMutation({ mutationFn: (b: CreateSummaryRequest) => meetings.createSummary(id, b), onSuccess: done }),
    deleteSummary: useMutation({ mutationFn: (sid: string) => meetings.deleteSummary(id, sid), onSuccess: done }),
    addActionItem: useMutation({ mutationFn: (b: CreateActionItemRequest) => meetings.addActionItem(id, b), onSuccess: done }),
    patchActionItem: useMutation({
      mutationFn: (p: { itemId: string; body: PatchActionItemRequest }) => meetings.patchActionItem(id, p.itemId, p.body),
      onMutate: async (p) => {
        // Belgilash darhol ko'rinsin (optimistik), xato bo'lsa qaytariladi.
        await qc.cancelQueries({ queryKey: qk.actionItems(id) });
        const prev = qc.getQueryData<{ items: ActionItem[] }>(qk.actionItems(id));
        if (prev && p.body.status) {
          qc.setQueryData(qk.actionItems(id), {
            items: prev.items.map((i) => (i.id === p.itemId ? { ...i, status: p.body.status! } : i)),
          });
        }
        return { prev };
      },
      onError: (_e, _p, ctx) => {
        if (ctx?.prev) qc.setQueryData(qk.actionItems(id), ctx.prev);
      },
      onSettled: () => {
        done();
        void qc.invalidateQueries({ queryKey: ['action-items'] });
      },
    }),
  };
}
