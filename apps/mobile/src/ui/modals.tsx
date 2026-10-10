/**
 * Android'da `Alert.prompt` yo'q - matn so'rash va ro'yxatdan tanlash uchun
 * o'zimizning kichik modallar.
 */
import { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useT } from '@/features/settings/settingsStore';

import { Button, Field } from './components';
import { useTheme } from './theme';

interface PromptProps {
  visible: boolean;
  title: string;
  initial?: string;
  placeholder?: string;
  multiline?: boolean;
  maxLength?: number;
  allowEmpty?: boolean;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}

export function PromptModal(props: PromptProps) {
  // Ichki qism faqat ochiq paytda mount bo'ladi - har ochilganda `initial` dan boshlanadi.
  return (
    <Modal visible={props.visible} transparent animationType="fade" onRequestClose={props.onCancel}>
      {props.visible ? <PromptBody {...props} /> : null}
    </Modal>
  );
}

function PromptBody(props: PromptProps) {
  const th = useTheme();
  const t = useT();
  const [value, setValue] = useState(props.initial ?? '');
  const canSave = props.allowEmpty || value.trim().length > 0;
  return (
    <View style={s.backdrop}>
      <View style={[s.sheet, { backgroundColor: th.surface }]}>
        <Text style={[s.title, { color: th.text }]}>{props.title}</Text>
        <Field
          testID="prompt-input"
          value={value}
          onChangeText={setValue}
          placeholder={props.placeholder}
          multiline={props.multiline}
          maxLength={props.maxLength}
          autoFocus
          style={props.multiline ? { minHeight: 100, textAlignVertical: 'top' } : undefined}
        />
        <View style={s.row}>
          <Button small variant="ghost" title={t('common.cancel')} onPress={props.onCancel} style={s.btn} />
          <Button small testID="prompt-save" title={t('common.save')} disabled={!canSave} onPress={() => props.onSubmit(value.trim())} style={s.btn} />
        </View>
      </View>
    </View>
  );
}

export interface PickerOption<T> {
  value: T;
  label: string;
  hint?: string;
  destructive?: boolean;
}

export function PickerModal<T>(props: {
  visible: boolean;
  title: string;
  options: PickerOption<T>[];
  onPick: (value: T) => void;
  onCancel: () => void;
}) {
  const th = useTheme();
  const t = useT();
  return (
    <Modal visible={props.visible} transparent animationType="fade" onRequestClose={props.onCancel}>
      <Pressable style={s.backdrop} onPress={props.onCancel}>
        <Pressable style={[s.sheet, { backgroundColor: th.surface }]} onPress={() => {}}>
          <Text style={[s.title, { color: th.text }]}>{props.title}</Text>
          <ScrollView style={{ maxHeight: 420 }}>
            {props.options.map((o, i) => (
              <Pressable
                key={i}
                testID={`pick-${i}`}
                accessibilityRole="button"
                onPress={() => props.onPick(o.value)}
                style={({ pressed }) => [s.option, { borderColor: th.border, opacity: pressed ? 0.6 : 1 }]}>
                <Text style={{ color: o.destructive ? th.danger : th.text, fontSize: 16 }}>{o.label}</Text>
                {o.hint ? <Text style={{ color: th.textMuted, fontSize: 12, marginTop: 2 }}>{o.hint}</Text> : null}
              </Pressable>
            ))}
          </ScrollView>
          <Button small variant="ghost" title={t('common.cancel')} onPress={props.onCancel} style={{ marginTop: 10 }} />
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'center', padding: 20 },
  sheet: { borderRadius: 14, padding: 16 },
  title: { fontSize: 17, fontWeight: '700', marginBottom: 12 },
  row: { flexDirection: 'row', justifyContent: 'flex-end' },
  btn: { marginLeft: 8 },
  option: { paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth },
});
