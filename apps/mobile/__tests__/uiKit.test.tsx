/**
 * UI to'plami (Claude uslubidagi qayta ishlanish poydevori): ListRow, ListGroup,
 * Collapsible/StepList, StatusPill/ProgressBar, IconButton, EmptyState, Avatar,
 * Button/Segmented belgilari, xavfsiz zona hook'i, ko'rinish qoidasi va yozuv soati.
 *
 * Belgilar Jest'da `icon-<Nom>` testID'li bo'sh View (jest.setup.js) - qaysi belgi
 * chizilganini shu orqali tekshiramiz.
 */
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react-native';
import { AudioLines, CircleDot, Mic, Plug, Sparkles } from 'lucide-react-native';
import { Text } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { meetingsVisible } from '@/features/nav/visibility';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useRecordingClock } from '@/features/recorder/useRecordingClock';
import { useSettings } from '@/features/settings/settingsStore';
import { Avatar, initialsOf } from '@/ui/Avatar';
import { Collapsible, StepList } from '@/ui/Collapsible';
import { Button, Segmented } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { IconButton } from '@/ui/IconButton';
import { IconTile } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { ListDivider, ListGroup, ListRow } from '@/ui/list';
import { ProgressBar, StatusPill } from '@/ui/StatusPill';
import { lightTheme } from '@/ui/theme';
import { hit, iconSize, radius, space, typography, type } from '@/ui/tokens';

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
  useRecorderStore.setState({ machine: initialRecorderState });
});

describe('tokens', () => {
  it('exposes the spec scale (and a parser-safe alias for `type`)', () => {
    expect(space.lg).toBe(16);
    expect(radius.lg).toBe(16);
    expect(iconSize.row).toBe(22);
    expect(hit).toEqual({ min: 44, row: 52 });
    expect(type.rowTitle).toEqual({ fontSize: 16, lineHeight: 21, fontWeight: '500' });
    expect(typography).toBe(type);
  });
});

describe('ListRow', () => {
  it('title + one subtitle line + chevron when pressable; press fires', async () => {
    const onPress = jest.fn();
    await render(<ListRow testID="row" icon={Plug} title="Ulanishlar" subtitle="HRM, CRM ulangan" onPress={onPress} />);
    expect(screen.getByText('Ulanishlar')).toBeTruthy();
    expect(screen.getByText('HRM, CRM ulangan').props.numberOfLines).toBe(1);
    expect(screen.getByTestId('icon-Plug')).toBeTruthy();
    expect(screen.getByTestId('icon-ChevronRight')).toBeTruthy();
    expect(screen.getByTestId('row').props.accessibilityRole).toBe('button');
    await fireEvent.press(screen.getByTestId('row'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('read-only row: no chevron, selectable subtitle is not clipped', async () => {
    await render(<ListRow title="Email" subtitle="y@brb.uz" selectableSubtitle />);
    expect(screen.queryByTestId('icon-ChevronRight')).toBeNull();
    const sub = screen.getByText('y@brb.uz');
    expect(sub.props.selectable).toBe(true);
    expect(sub.props.numberOfLines).toBeUndefined();
  });

  it('subtitleTone colors the value; destructive has no chevron and uses danger', async () => {
    await render(
      <>
        <ListRow title="Ulanishlar" subtitle="CRM: qayta kirish kerak" subtitleTone="warn" onPress={() => {}} />
        <ListRow testID="logout" title="Chiqish" destructive onPress={() => {}} />
      </>,
    );
    expect(screen.getByText('CRM: qayta kirish kerak')).toHaveStyle({ color: lightTheme.tones.warn.fg });
    expect(screen.getByText('Chiqish')).toHaveStyle({ color: lightTheme.danger });
    // Faqat birinchi qatorda chevron.
    expect(screen.getAllByTestId('icon-ChevronRight')).toHaveLength(1);
  });

  it('disabled row does not fire and reports disabled', async () => {
    const onPress = jest.fn();
    await render(<ListRow testID="row" title="Chiqish" destructive disabled onPress={onPress} />);
    await fireEvent.press(screen.getByTestId('row'));
    expect(onPress).not.toHaveBeenCalled();
    expect(screen.getByTestId('row')).toBeDisabled();
  });

  it('switch: role switch + checked; the switch and the whole row both toggle', async () => {
    const onChange = jest.fn();
    await render(
      <ListRow testID="row" title='"Yozish" belgisi' right={{ kind: 'switch', value: false, onChange, testID: 'launcher-toggle' }} />,
    );
    const row = screen.getByTestId('row');
    expect(row.props.accessibilityRole).toBe('switch');
    expect(row).not.toBeChecked();
    await fireEvent(screen.getByTestId('launcher-toggle'), 'valueChange', true);
    expect(onChange).toHaveBeenLastCalledWith(true);
    await fireEvent.press(row);
    expect(onChange).toHaveBeenLastCalledWith(true);
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it('disabled switch row does not toggle', async () => {
    const onChange = jest.fn();
    await render(<ListRow testID="row" title="X" right={{ kind: 'switch', value: true, onChange, disabled: true }} />);
    expect(screen.getByTestId('row')).toBeChecked();
    await fireEvent.press(screen.getByTestId('row'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('check rows are radios with checked state and a check mark only when checked', async () => {
    await render(
      <>
        <ListRow testID="uilang-uz" title="O'zbekcha" right={{ kind: 'check', checked: true }} onPress={() => {}} />
        <ListRow testID="uilang-ru" title="Русский" right={{ kind: 'check', checked: false }} onPress={() => {}} />
      </>,
    );
    expect(screen.getByTestId('uilang-uz').props.accessibilityRole).toBe('radio');
    expect(screen.getByTestId('uilang-uz')).toBeChecked();
    expect(screen.getByTestId('uilang-ru')).not.toBeChecked();
    expect(screen.getAllByTestId('icon-Check')).toHaveLength(1);
    expect(screen.queryByTestId('icon-ChevronRight')).toBeNull();
  });

  it('pill right puts its testID on the text; value and node accessories render', async () => {
    await render(
      <>
        <ListRow title="HRM" right={{ kind: 'pill', label: 'Ulangan', tone: 'good', testID: 'conn-hrm' }} />
        <ListRow title="Versiya" right={{ kind: 'value', text: '1.1.1' }} />
        <ListRow title="Navbat" right={{ kind: 'node', node: <Text>tugma</Text> }} />
      </>,
    );
    expect(screen.getByTestId('conn-hrm')).toHaveTextContent('Ulangan');
    expect(screen.getByText('1.1.1')).toBeTruthy();
    expect(screen.getByText('tugma')).toBeTruthy();
  });

  it('plain selected row: selected state, bold title; long-press fires', async () => {
    const onLongPress = jest.fn();
    await render(<ListRow testID="history-1" variant="plain" selected title="Ta'til qoldig'i" onPress={() => {}} onLongPress={onLongPress} />);
    expect(screen.getByTestId('history-1')).toBeSelected();
    expect(screen.getByText("Ta'til qoldig'i")).toHaveStyle({ fontWeight: '600' });
    await fireEvent(screen.getByTestId('history-1'), 'longPress');
    expect(onLongPress).toHaveBeenCalled();
  });

  it('leading replaces the icon', async () => {
    await render(<ListRow title="Yusuf" icon={Plug} leading={<Avatar name="Yusuf Mamajonov" testID="av" />} />);
    expect(screen.getByTestId('av')).toBeTruthy();
    expect(screen.queryByTestId('icon-Plug')).toBeNull();
  });
});

describe('ListGroup / ListDivider', () => {
  it('renders header, rows and footer', async () => {
    await render(
      <ListGroup testID="g" header="Telefonda saqlash" footer="Izoh">
        <ListRow title="A" />
        <ListRow title="B" />
      </ListGroup>,
    );
    expect(screen.getByText('Telefonda saqlash')).toBeTruthy();
    expect(screen.getByText('Izoh')).toBeTruthy();
    expect(screen.getByText('A')).toBeTruthy();
    expect(screen.getByText('B')).toBeTruthy();
    await render(<ListDivider />);
  });
});

describe('Collapsible / StepList', () => {
  it('uncontrolled: closed by default, toggles content and expanded state', async () => {
    await render(
      <Collapsible testID="quick-limits" title="Cheklovlar">
        <Text>ichida</Text>
      </Collapsible>,
    );
    const header = screen.getByTestId('quick-limits');
    expect(header).not.toBeExpanded();
    expect(screen.queryByText('ichida')).toBeNull();
    expect(screen.getByTestId('icon-ChevronDown')).toBeTruthy();
    await fireEvent.press(header);
    expect(screen.getByTestId('quick-limits')).toBeExpanded();
    expect(screen.getByTestId('quick-limits-content')).toBeTruthy();
    expect(screen.getByText('ichida')).toBeTruthy();
    expect(screen.getByTestId('icon-ChevronUp')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('quick-limits'));
    expect(screen.queryByText('ichida')).toBeNull();
  });

  it('initiallyOpen and controlled mode', async () => {
    const onToggle = jest.fn();
    await render(
      <>
        <Collapsible testID="a" title="A" initiallyOpen>
          <Text>a-body</Text>
        </Collapsible>
        <Collapsible testID="b" title="B" open={false} onToggle={onToggle}>
          <Text>b-body</Text>
        </Collapsible>
      </>,
    );
    expect(screen.getByText('a-body')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('b'));
    expect(onToggle).toHaveBeenCalledWith(true);
    // Boshqariladigan: ota `open` ni o'zgartirmaguncha yopiq qoladi.
    expect(screen.queryByText('b-body')).toBeNull();
  });

  it('StepList numbers items or shows bullets', async () => {
    await render(<StepList testID="steps" items={['Birinchi', 'Ikkinchi']} />);
    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText('Ikkinchi')).toBeTruthy();
    await render(<StepList items={['Faqat nuqta']} numbered={false} />);
    expect(screen.queryByText('1')).toBeNull();
    expect(screen.getByText('Faqat nuqta')).toBeTruthy();
  });
});

describe('StatusPill / ProgressBar', () => {
  it('textTestID lands on the inner Text (keeps `volume-status` readable)', async () => {
    await render(<StatusPill testID="pill" textTestID="volume-status" label="Yoqilgan" tone="good" icon={Mic} />);
    const text = screen.getByTestId('volume-status');
    expect(text).toHaveTextContent('Yoqilgan');
    expect(text).toHaveStyle({ color: lightTheme.tones.good.fg });
    expect(screen.getByTestId('pill')).toHaveStyle({ backgroundColor: lightTheme.tones.good.bg });
    expect(screen.getByTestId('icon-Mic')).toBeTruthy();
  });

  it('record tone is red on the bad background', async () => {
    await render(<StatusPill testID="pill" label="Yozilmoqda" tone="record" dot />);
    expect(screen.getByText('Yozilmoqda')).toHaveStyle({ color: lightTheme.record });
    expect(screen.getByTestId('pill')).toHaveStyle({ backgroundColor: lightTheme.tones.bad.bg });
  });

  it('ProgressBar: known value reports percent; unknown has no value', async () => {
    await render(<ProgressBar testID="p1" value={0.42} tone="info" />);
    expect(screen.getByTestId('p1')).toHaveAccessibilityValue({ min: 0, max: 100, now: 42 });
    await render(<ProgressBar testID="p2" value={null} />);
    expect(screen.getByTestId('p2').props.accessibilityValue).toBeUndefined();
  });
});

describe('IconButton / IconTile / Avatar', () => {
  it('IconButton: label is the accessible name, press and disabled work', async () => {
    const onPress = jest.fn();
    await render(<IconButton testID="chat-meetings" icon={AudioLines} label="Yozuvlar" onPress={onPress} />);
    expect(screen.getByRole('button', { name: 'Yozuvlar' })).toBeTruthy();
    await fireEvent.press(screen.getByTestId('chat-meetings'));
    expect(onPress).toHaveBeenCalled();
    const off = jest.fn();
    await render(<IconButton testID="x" icon={AudioLines} label="X" onPress={off} disabled />);
    await fireEvent.press(screen.getByTestId('x'));
    expect(off).not.toHaveBeenCalled();
  });

  it('IconTile tones', async () => {
    await render(<IconTile testID="t" icon={CircleDot} tone="record" size="lg" />);
    expect(screen.getByTestId('t')).toHaveStyle({ width: 56, height: 56, backgroundColor: lightTheme.tones.bad.bg });
    expect(screen.getByTestId('icon-CircleDot')).toBeTruthy();
  });

  it('Avatar initials (same rule as the old chat/settings helpers)', async () => {
    expect(initialsOf('Yusuf Mamajonov')).toBe('YM');
    expect(initialsOf('  aziz ')).toBe('A');
    expect(initialsOf(null)).toBe('·');
    await render(<Avatar name="Yusuf Mamajonov" size={48} testID="av" />);
    expect(screen.getByText('YM')).toBeTruthy();
    expect(screen.getByTestId('av')).toHaveStyle({ width: 48, borderRadius: 24 });
  });
});

describe('EmptyState', () => {
  it('icon, title, body, primary and secondary actions', async () => {
    const start = jest.fn();
    const quick = jest.fn();
    await render(
      <EmptyState
        icon={Mic}
        tone="record"
        title="Hali yozuv yo'q"
        body="Yig'ilishni yozing"
        action={{ title: 'Yozish', onPress: start, variant: 'record', icon: CircleDot, testID: 'meetings-empty-record' }}
        secondary={{ title: 'Tez yozishni sozlash', onPress: quick, testID: 'empty-quick' }}
      />,
    );
    expect(screen.getByText("Hali yozuv yo'q")).toBeTruthy();
    expect(screen.getByText("Yig'ilishni yozing")).toBeTruthy();
    expect(screen.getByTestId('icon-Mic')).toBeTruthy();
    expect(screen.getByTestId('icon-CircleDot')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('meetings-empty-record'));
    await fireEvent.press(screen.getByTestId('empty-quick'));
    expect(start).toHaveBeenCalled();
    expect(quick).toHaveBeenCalled();
  });
});

describe('components.tsx additions (backward compatible)', () => {
  it('Button keeps its plain title and gains an icon + pill shape', async () => {
    await render(<Button testID="b1" title="Oddiy" />);
    expect(screen.getByText('Oddiy')).toBeTruthy();
    await render(<Button testID="b2" title="Yozish" icon={CircleDot} pill variant="record" />);
    expect(screen.getByText('Yozish')).toBeTruthy();
    expect(screen.getByTestId('icon-CircleDot')).toBeTruthy();
    expect(screen.getByTestId('b2')).toHaveStyle({ borderRadius: 999 });
  });

  it('Segmented options can carry icons; testIDs and selection unchanged', async () => {
    const onChange = jest.fn();
    await render(
      <Segmented
        testIDPrefix="tab"
        iconPosition="top"
        value="summary"
        onChange={onChange}
        options={[
          { value: 'summary', label: 'Xulosa', icon: Sparkles },
          { value: 'transcript', label: 'Matn' },
        ]}
      />,
    );
    expect(screen.getByTestId('icon-Sparkles')).toBeTruthy();
    expect(screen.getByTestId('tab-summary')).toBeSelected();
    await fireEvent.press(screen.getByTestId('tab-transcript'));
    expect(onChange).toHaveBeenCalledWith('transcript');
  });
});

describe('hooks', () => {
  it('useSafeInsets: zeros without a provider, real insets with one', async () => {
    const bare = await renderHook(() => useSafeInsets());
    expect(bare.result.current).toEqual({ top: 0, bottom: 0, left: 0, right: 0 });
    const metrics = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 24, left: 0, right: 0, bottom: 16 } };
    const wrapped = await renderHook(() => useSafeInsets(), {
      wrapper: ({ children }) => <SafeAreaProvider initialMetrics={metrics}>{children}</SafeAreaProvider>,
    });
    expect(wrapped.result.current).toMatchObject({ top: 24, bottom: 16 });
  });

  it('meetingsVisible: config OR live recording OR local rows', () => {
    expect(meetingsVisible({ configured: false, live: false, localRows: 0 })).toBe(false);
    expect(meetingsVisible({ configured: true, live: false, localRows: 0 })).toBe(true);
    expect(meetingsVisible({ configured: false, live: true, localRows: 0 })).toBe(true);
    // Internetsiz ochilgan ilova: konfig yo'q, lekin telefonda yozuv bor.
    expect(meetingsVisible({ configured: false, live: false, localRows: 2 })).toBe(true);
  });

  it('useRecordingClock: ticks while recording, freezes while paused', async () => {
    jest.useFakeTimers({ now: 1_000_000 });
    try {
      const { result } = await renderHook(() => useRecordingClock());
      expect(result.current).toEqual({ live: false, paused: false, label: '00:00' });
      await act(async () => {
        useRecorderStore.setState({
          machine: { ...initialRecorderState, status: 'recording', startedAt: 1_000_000 - 72_000, segmentStartedAt: 1_000_000 - 72_000 },
        });
      });
      // Mount paytidagi `now` dan: 1:12.
      expect(result.current).toEqual({ live: true, paused: false, label: '01:12' });
      await act(async () => {
        jest.advanceTimersByTime(3_000);
      });
      expect(result.current.label).toBe('01:15');
      await act(async () => {
        useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'paused', accumulatedMs: 80_000, segmentStartedAt: null } });
      });
      expect(result.current).toEqual({ live: true, paused: true, label: '01:20' });
      await act(async () => {
        jest.advanceTimersByTime(5_000);
      });
      expect(result.current.label).toBe('01:20');
    } finally {
      jest.useRealTimers();
    }
  });
});
