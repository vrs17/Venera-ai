/**
 * Savol tabi (spec 7.4, 3.2 #26-27): bitta yig'ilish bo'yicha javob,
 * manbalar (citation) chiplari audio/transkriptga o'tkazadi, keyingi savol
 * takliflari va tarix. Javob - markdown (v3 `**qalin**`, ro'yxatlar): `MarkdownLite`
 * bilan chiziladi, yulduzcha va panjaralar xom ko'rinmaydi.
 */
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import type { AskAnswer, Meeting, Speaker } from '@/api/types';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { Banner, Button, Card, Chip, EvidenceChip, Field, Muted, styles as ui } from '@/ui/components';
import { MarkdownLite } from '@/ui/markdown';
import { useTheme } from '@/ui/theme';

import { useMeetingMutations, useQuestions } from './queries';
import { renderTokens, speakerLabel } from './renderTokens';

export function AskView({ meeting, speakers, onSeek }: { meeting: Meeting; speakers: Speaker[]; onSeek?: (t: number) => void }) {
  const t = useT();
  const lang = useSettings((s) => s.uiLang);
  const ready = meeting.transcript.available;
  const history = useQuestions(meeting.id, ready);
  const { ask } = useMeetingMutations(meeting.id);
  const [question, setQuestion] = useState('');

  if (!ready) return <Banner tone="info" text={t('ask.notReady')} />;

  const send = (q: string) => {
    const text = q.trim().slice(0, 500);
    if (!text || ask.isPending) return;
    ask.mutate({ question: text, language: lang });
    setQuestion('');
  };

  const quick = [
    { label: t('ask.quick.tasks'), q: t('ask.quick.tasksQ') },
    { label: t('ask.quick.decisions'), q: t('ask.quick.decisionsQ') },
    { label: t('ask.quick.followUp'), q: t('ask.quick.followUpQ') },
  ];

  const items: AskAnswer[] = history.data?.items ?? [];
  const errCode = ask.error instanceof ApiError ? ask.error.code : null;

  return (
    <View>
      <Field testID="ask-input" placeholder={t('ask.placeholder')} value={question} onChangeText={setQuestion} maxLength={500} multiline />
      <View style={[ui.row, { marginBottom: 8 }]}>
        <Button testID="ask-send" title={t('ask.send')} disabled={!question.trim()} loading={ask.isPending} onPress={() => send(question)} />
      </View>
      <View style={[ui.wrap, { marginBottom: 10 }]}>
        {quick.map((c) => (
          <Chip key={c.label} label={c.label} tone="info" onPress={() => send(c.q)} />
        ))}
      </View>
      {ask.error ? (
        <Banner
          tone="bad"
          text={
            errCode === 'rate_limited'
              ? t('err.rate_limited')
              : errCode === 'llm_unavailable'
                ? t('err.llm_unavailable')
                : (ask.error as Error).message || t('common.error')
          }
        />
      ) : null}
      {items.length === 0 ? <Muted>{t('ask.empty')}</Muted> : null}
      {items.map((a) => (
        <AnswerCard key={a.id} answer={a} speakers={speakers} lang={lang} onSeek={onSeek} onFollowUp={send} />
      ))}
    </View>
  );
}

function AnswerCard({
  answer,
  speakers,
  lang,
  onSeek,
  onFollowUp,
}: {
  answer: AskAnswer;
  speakers: Speaker[];
  lang: 'uz' | 'ru' | 'en';
  onSeek?: (t: number) => void;
  onFollowUp: (q: string) => void;
}) {
  const th = useTheme();
  return (
    <Card>
      <Text style={[s.q, { color: th.textMuted }]}>{answer.question}</Text>
      <MarkdownLite text={renderTokens(answer.answer, speakers, lang)} />
      {answer.citations.length ? (
        <View style={ui.wrap}>
          {answer.citations.map((c) => (
            <View key={c.segmentId} style={s.cite}>
              <EvidenceChip start={c.start} onSeek={onSeek} />
              <Text numberOfLines={2} style={[s.citeText, { color: th.textMuted }]}>
                {c.speaker ? `${speakerLabel(c.speaker, speakers, lang)}: ` : ''}
                {c.text}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
      {answer.followUps.length ? (
        <View style={ui.wrap}>
          {answer.followUps.map((f) => (
            <Chip key={f} label={f} tone="accent" onPress={() => onFollowUp(f)} />
          ))}
        </View>
      ) : null}
    </Card>
  );
}

const s = StyleSheet.create({
  q: { fontSize: 13, fontWeight: '600', marginBottom: 6 },
  cite: { width: '100%', flexDirection: 'row', alignItems: 'center', marginTop: 4 },
  citeText: { flex: 1, fontSize: 12, marginLeft: 4 },
});
