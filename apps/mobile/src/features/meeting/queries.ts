/**
 * React Query hook'lari (server holati). Polling qoidasi spec 3.2 #7:
 * server `pollAfterSec` beradi (3/10/5/600 s), `ready`/`failed` da null -
 * polling to'xtaydi.
 *
 * Mutatsiya xatolari: `_layout.tsx` dagi `MutationCache.onError` HAR BIRINI
 * toast bilan ko'rsatadi (kod -> i18n `err.<code>`). Xatoni o'zi ko'rsatadigan
 * mutatsiya `meta: { silentError: true }` beradi.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import type {
  ActionItem,
  CreateActionItemRequest,
  CreateSummaryRequest,
  Lang,
  Meeting,
  PatchActionItemRequest,
  PatchMeetingRequest,
  PatchSegmentRequest,
  Transcript,
} from '@/api/types';
import { useServices } from '@/services';

export const qk = {
  config: ['meetings', 'config'] as const,
  list: (q: string) => ['meetings', 'list', q] as const,
  meeting: (id: string) => ['meetings', id] as const,
  transcript: (id: string) => ['meetings', id, 'transcript'] as const,
  summaries: (id: string) => ['meetings', id, 'summaries'] as const,
  summary: (id: string, sid: string) => ['meetings', id, 'summaries', sid] as const,
  actionItems: (id: string) => ['meetings', id, 'action-items'] as const,
  questions: (id: string) => ['meetings', id, 'questions'] as const,
  myItems: (status: string) => ['action-items', status] as const,
};

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

export function useQuestions(id: string | null, enabled = true) {
  const { meetings } = useServices();
  return useQuery({
    queryKey: qk.questions(id ?? ''),
    queryFn: () => meetings.questions(id as string),
    enabled: !!id && enabled,
  });
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
    ask: useMutation({
      // AskView xatoni o'zi (javob joyida) ko'rsatadi - global toast kerak emas.
      meta: { silentError: true },
      mutationFn: (p: { question: string; language?: Lang }) => meetings.ask(id, p),
      onSuccess: () => void qc.invalidateQueries({ queryKey: qk.questions(id) }),
    }),
  };
}
