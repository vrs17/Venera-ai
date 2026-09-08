// Inline stroke SVG icons — paths copied verbatim from the design prototype handoff.
//
// Each icon is a Vue functional component, kept in one module so import sites
// match the original React file 1:1. Only the transform props (size -> width
// /height, stroke -> path colour) are read explicitly; any `style` / `class`
// / aria-* a caller passes falls through to the root <svg> automatically.

import { h } from 'vue'
import type { FunctionalComponent } from 'vue'

export const ChevronDownIcon: FunctionalComponent<{ size?: number; stroke?: string }> = (props) =>
  h('svg', { width: props.size ?? 10, height: props.size ?? 10, viewBox: '0 0 10 10', fill: 'none' }, [
    h('path', {
      d: 'M2 3.5l3 3 3-3',
      stroke: props.stroke ?? '#8A867F',
      'stroke-width': '1.6',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
ChevronDownIcon.props = ['size', 'stroke']

/* ---- Welcome chip icons ---- */

export const DocChipIcon: FunctionalComponent = () =>
  h('svg', { width: 20, height: 20, viewBox: '0 0 20 20', fill: 'none' }, [
    h('path', {
      d: 'M5 2.5h7l3.5 3.5V17a0.8 0.8 0 0 1-0.8 0.8H5a0.8 0.8 0 0 1-0.8-0.8V3.3A0.8 0.8 0 0 1 5 2.5z',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M7 9h6M7 12h6M7 15h4', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])

export const CodeChipIcon: FunctionalComponent = () =>
  h('svg', { width: 20, height: 20, viewBox: '0 0 20 20', fill: 'none' }, [
    h('path', {
      d: 'M7 5.5L2.8 10 7 14.5M13 5.5l4.2 4.5-4.2 4.5',
      stroke: 'currentColor',
      'stroke-width': '1.6',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])

export const CardChipIcon: FunctionalComponent = () =>
  h('svg', { width: 20, height: 20, viewBox: '0 0 20 20', fill: 'none' }, [
    h('rect', { x: '2.5', y: '4.5', width: '15', height: '11', rx: '2', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', { d: 'M2.5 8.5h15', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', { d: 'M5.5 12.5h4', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])

export const CalendarChipIcon: FunctionalComponent = () =>
  h('svg', { width: 20, height: 20, viewBox: '0 0 20 20', fill: 'none' }, [
    h('rect', { x: '3', y: '4', width: '14', height: '13', rx: '2', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', { d: 'M3 8h14M7 2.5V5M13 2.5V5', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' }),
    h('circle', { cx: '10', cy: '12.5', r: '1.8', stroke: 'currentColor', 'stroke-width': '1.4' }),
  ])

/* ---- Input dock icons ---- */

export const AttachIcon: FunctionalComponent = () =>
  h('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' }, [
    h('path', { d: 'M8 3v10M3 8h10', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round' }),
  ])

export const MicIcon: FunctionalComponent = () =>
  h('svg', { width: 15, height: 15, viewBox: '0 0 16 16', fill: 'none' }, [
    h('rect', { x: '6', y: '1.5', width: '4', height: '8', rx: '2', stroke: 'currentColor', 'stroke-width': '1.4' }),
    h('path', {
      d: 'M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2.5',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
    }),
  ])

/** Ovoz chiqayotganini bildiradi: karnay va ikkita to'lqin. Mikrofon bilan
 *  yonma-yon turadi, shuning uchun bir xil 16x16 to'rda chizilgan. */
export const SpeakerIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 15, height: props.size ?? 15, viewBox: '0 0 16 16', fill: 'none' }, [
    h('path', {
      d: 'M8.5 2.5 5 5.5H2.5v5H5l3.5 3z',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linejoin': 'round',
    }),
    h('path', {
      d: 'M11 5.5a3.5 3.5 0 0 1 0 5M13 3.5a6.5 6.5 0 0 1 0 9',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
    }),
  ])

export const GlobeIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 15, height: props.size ?? 15, viewBox: '0 0 18 18', fill: 'none' }, [
    h('circle', { cx: '9', cy: '9', r: '6.6', stroke: 'currentColor', 'stroke-width': '1.4' }),
    h('path', {
      d: 'M2.4 9h13.2M9 2.4c2 2.1 2 11.1 0 13.2M9 2.4c-2 2.1-2 11.1 0 13.2',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
GlobeIcon.props = ['size']

/* ---- Theme toggle icons ---- */

export const SunIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('circle', { cx: '9', cy: '9', r: '3.4', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', {
      d: 'M9 1.6v2M9 14.4v2M1.6 9h2M14.4 9h2M3.7 3.7l1.4 1.4M12.9 12.9l1.4 1.4M14.3 3.7l-1.4 1.4M5.1 12.9l-1.4 1.4',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
    }),
  ])
SunIcon.props = ['size']

export const MoonIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M15 10.6A6.4 6.4 0 1 1 7.4 3a5 5 0 0 0 7.6 7.6z',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linejoin': 'round',
    }),
  ])
MoonIcon.props = ['size']

export const SendIcon: FunctionalComponent<{ stroke: string }> = (props) =>
  h('svg', { width: 15, height: 15, viewBox: '0 0 16 16', fill: 'none' }, [
    h('path', {
      d: 'M8 13V3M3.5 7.5L8 3l4.5 4.5',
      stroke: props.stroke,
      'stroke-width': '1.8',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
SendIcon.props = ['stroke']

export const StopIcon: FunctionalComponent<{ size?: number; fill?: string }> = (props) =>
  h('svg', { width: props.size ?? 14, height: props.size ?? 14, viewBox: '0 0 16 16', fill: 'none' }, [
    h('rect', { x: '3', y: '3', width: '10', height: '10', rx: '1.8', fill: props.fill ?? 'currentColor' }),
  ])
StopIcon.props = ['size', 'fill']

/* ---- Status / utility icons ---- */

export const CheckIcon: FunctionalComponent<{ size?: number; stroke?: string }> = (props) =>
  h('svg', { width: props.size ?? 14, height: props.size ?? 14, viewBox: '0 0 16 16', fill: 'none' }, [
    h('path', {
      d: 'M3 8.5l3.2 3L13 5',
      stroke: props.stroke ?? '#1E8E3E',
      'stroke-width': '1.8',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
CheckIcon.props = ['size', 'stroke']

export const ShieldIcon: FunctionalComponent<{ size?: number; stroke?: string }> = (props) => {
  const stroke = props.stroke ?? '#C42814'
  return h('svg', { width: props.size ?? 14, height: props.size ?? 14, viewBox: '0 0 16 16', fill: 'none' }, [
    h('path', {
      d: 'M8 1.6l5 1.6V8c0 3-2.2 5.4-5 6.4-2.8-1-5-3.4-5-6.4V3.2L8 1.6z',
      stroke,
      'stroke-width': '1.4',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M8 6v3', stroke, 'stroke-width': '1.5', 'stroke-linecap': 'round' }),
    h('circle', { cx: '8', cy: '11', r: '0.6', fill: stroke }),
  ])
}
ShieldIcon.props = ['size', 'stroke']

export const LockIcon: FunctionalComponent<{ size?: number; stroke?: string }> = (props) => {
  const stroke = props.stroke ?? '#B8761A'
  return h('svg', { width: props.size ?? 14, height: props.size ?? 14, viewBox: '0 0 16 16', fill: 'none' }, [
    h('rect', { x: '3', y: '7', width: '10', height: '7', rx: '1.6', stroke, 'stroke-width': '1.4' }),
    h('path', { d: 'M5 7V5a3 3 0 0 1 6 0v2', stroke, 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])
}
LockIcon.props = ['size', 'stroke']

export const PencilIcon: FunctionalComponent<{ size?: number; stroke?: string }> = (props) =>
  h('svg', { width: props.size ?? 13, height: props.size ?? 13, viewBox: '0 0 16 16', fill: 'none' }, [
    h('path', {
      d: 'M11.5 2.5l2 2L5.8 12.2l-2.5 0.5 0.5-2.5 7.7-7.7z',
      stroke: props.stroke ?? '#9AA0A6',
      'stroke-width': '1.4',
      'stroke-linejoin': 'round',
    }),
  ])
PencilIcon.props = ['size', 'stroke']

/* ---- Auth icons (inherit colour via currentColor) ---- */

export const MailIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('rect', { x: '2', y: '4', width: '14', height: '10', rx: '2', stroke: 'currentColor', 'stroke-width': '1.4' }),
    h('path', {
      d: 'M2.6 5L9 9.5 15.4 5',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
MailIcon.props = ['size']

export const UserIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('circle', { cx: '9', cy: '6', r: '3', stroke: 'currentColor', 'stroke-width': '1.4' }),
    h('path', { d: 'M3.6 15a5.4 5.4 0 0 1 10.8 0', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])
UserIcon.props = ['size']

export const EyeIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M1.5 9S4 3.8 9 3.8 16.5 9 16.5 9 14 14.2 9 14.2 1.5 9 1.5 9z',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linejoin': 'round',
    }),
    h('circle', { cx: '9', cy: '9', r: '2.3', stroke: 'currentColor', 'stroke-width': '1.4' }),
  ])
EyeIcon.props = ['size']

export const EyeOffIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M3.5 4.2C2.1 5.4 1.5 9 1.5 9s2.5 5.2 7.5 5.2c1.2 0 2.3-.3 3.2-.8M7.1 4.1A7 7 0 0 1 9 3.8c5 0 7.5 5.2 7.5 5.2a13.6 13.6 0 0 1-2 2.6',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M7.4 7.4a2.3 2.3 0 0 0 3.2 3.2', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
    h('path', { d: 'M3 3l12 12', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])
EyeOffIcon.props = ['size']

export const ArrowLeftIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M10.5 4L6 9l4.5 5M6 9h7.5',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
ArrowLeftIcon.props = ['size']

/* ---- Auth form-header icons (sit in the gradient badge; inherit white) ---- */

export const LoginIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M10.5 2.5H14a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5h-3.5',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', {
      d: 'M2.5 9h8M7.5 5.5 11 9l-3.5 3.5',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
LoginIcon.props = ['size']

export const UserPlusIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('circle', { cx: '7', cy: '6', r: '3', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', { d: 'M2 15a5 5 0 0 1 10 0', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' }),
    h('path', { d: 'M14 4.5v4M12 6.5h4', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' }),
  ])
UserPlusIcon.props = ['size']

export const KeyIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('circle', { cx: '6', cy: '6', r: '3.3', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', {
      d: 'M8.4 8.4 15 15M12.3 12.3l1.5-1.5M13.9 13.9l1.4-1.4',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
KeyIcon.props = ['size']

export const MenuIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 18, height: props.size ?? 18, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', { d: 'M3 5h12M3 9h12M3 13h12', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round' }),
  ])
MenuIcon.props = ['size']

export const PlusIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', { d: 'M9 3.5v11M3.5 9h11', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round' }),
  ])
PlusIcon.props = ['size']

export const PanelLeftIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 18, height: props.size ?? 18, viewBox: '0 0 18 18', fill: 'none' }, [
    h('rect', { x: '2.5', y: '3.5', width: '13', height: '11', rx: '2.5', stroke: 'currentColor', 'stroke-width': '1.5' }),
    h('path', { d: 'M7 3.5v11', stroke: 'currentColor', 'stroke-width': '1.5' }),
  ])
PanelLeftIcon.props = ['size']

/** "Salom Venera" tinglash uchun: to'lqinlarga qaragan quloq. Mikrofon
 *  belgisi ATAYLAB emas - u "hozir yozilmoqda" degan ma'noni beradi, bu esa
 *  doimiy tinglash rejimini yoqish/o'chirish tugmasi. */
export const EarIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M5.5 7a3.5 3.5 0 1 1 7 0c0 2-1.8 2.6-2.4 3.7-.4.8-.2 1.6-.9 2.2-.7.6-1.9.4-2.3-.4',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', {
      d: 'M8 7.2a1.1 1.1 0 0 1 2.1.3',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
    }),
  ])

export const CodeIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M6.5 4.5 2.5 9l4 4.5M11.5 4.5 15.5 9l-4 4.5',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
CodeIcon.props = ['size']

export const LogOutIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M7 2.5H4A1.5 1.5 0 0 0 2.5 4v10A1.5 1.5 0 0 0 4 15.5h3',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', {
      d: 'M10 9h6.5M14 6.5 16.5 9 14 11.5',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
LogOutIcon.props = ['size']

export const CopyIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 15, height: props.size ?? 15, viewBox: '0 0 24 24', fill: 'none' }, [
    h('rect', { x: '8', y: '8', width: '13', height: '13', rx: '2.5', stroke: 'currentColor', 'stroke-width': '1.8' }),
    h('path', {
      d: 'M4.5 15.5A2 2 0 0 1 3 13.6V5A2 2 0 0 1 5 3h8.6a2 2 0 0 1 1.9 1.5',
      stroke: 'currentColor',
      'stroke-width': '1.8',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  ])
CopyIcon.props = ['size']

export const RegenerateIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 15, height: props.size ?? 15, viewBox: '0 0 24 24', fill: 'none' }, [
    h('path', {
      d: 'M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8',
      stroke: 'currentColor',
      'stroke-width': '1.8',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M3 3v5h5', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }),
    h('path', {
      d: 'M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16',
      stroke: 'currentColor',
      'stroke-width': '1.8',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M21 21v-5h-5', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }),
  ])
RegenerateIcon.props = ['size']

export const FileTextIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 20 20', fill: 'none' }, [
    h('path', {
      d: 'M5 2.5h7l3.5 3.5V17a0.8 0.8 0 0 1-0.8 0.8H5a0.8 0.8 0 0 1-0.8-0.8V3.3A0.8 0.8 0 0 1 5 2.5z',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M11.5 2.6V6.2H15', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linejoin': 'round' }),
    h('path', { d: 'M7 10h6M7 13h4', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])
FileTextIcon.props = ['size']

export const DownloadIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 16, height: props.size ?? 16, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M9 2.5v8M5.5 7 9 10.5 12.5 7',
      stroke: 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    h('path', { d: 'M3.5 13.5h11', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' }),
  ])
DownloadIcon.props = ['size']

/* ---- Platform marks (desktop download cards) ---- */

// To'ldirilgan belgilar: platforma logotipi konturda o'z shaklini yo'qotadi,
// shuning uchun `fill: currentColor` — rangni ota element boshqaradi.
export const WindowsIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 18, height: props.size ?? 18, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M2 4.2 8.2 3.3v5.1H2V4.2zM9.3 3.15 16 2.2v6.2H9.3V3.15zM2 9.5h6.2v5.1L2 13.75V9.5zM9.3 9.5H16v6.3l-6.7-.95V9.5z',
      fill: 'currentColor',
    }),
  ])
WindowsIcon.props = ['size']

export const AppleIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 18, height: props.size ?? 18, viewBox: '0 0 24 24', fill: 'none' }, [
    h('path', {
      d: 'M16.365 1.43c0 1.14-.493 2.27-1.177 3.08-.744.9-1.99 1.57-2.987 1.49-.12-1.03.42-2.15 1.07-2.87.73-.83 2.02-1.44 3.094-1.7zM20.5 17.36c-.55 1.27-.81 1.84-1.52 2.96-.99 1.56-2.38 3.5-4.1 3.51-1.53.02-1.92-.99-4-.98-2.08.01-2.51 1-4.04.98-1.72-.02-3.04-1.77-4.03-3.33C0 16.13-.29 10.9 1.4 8.12c1.2-1.98 3.1-3.14 4.88-3.14 1.82 0 2.96 1 4.47 1 1.46 0 2.35-1 4.45-1 1.6 0 3.28.87 4.48 2.37-3.94 2.16-3.3 7.79.82 10.01z',
      fill: 'currentColor',
    }),
  ])
AppleIcon.props = ['size']

/** Audio bars — the "voice mode" mark. Bars, not a mic: the mic to its left
 *  already means "dictate one message", and two microphones side by side would
 *  read as the same action twice. */
export const ConversationIcon: FunctionalComponent<{ size?: number }> = (props) => {
  const size = props.size ?? 18
  // Heights are deliberately uneven — evenly stepped bars read as a chart.
  const bars: [number, number][] = [
    [4.5, 5],
    [7.5, 9],
    [10.5, 13],
    [13.5, 7],
  ]
  return h(
    'svg',
    { width: size, height: size, viewBox: '0 0 18 18', fill: 'none' },
    bars.map(([x, height]) =>
      h('rect', {
        key: x,
        x: x - 0.9,
        y: (18 - height) / 2,
        width: 1.8,
        height,
        rx: 0.9,
        fill: 'currentColor',
      }),
    ),
  )
}

export const XIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 18, height: props.size ?? 18, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M4.5 4.5l9 9M13.5 4.5l-9 9',
      stroke: 'currentColor',
      'stroke-width': '1.6',
      'stroke-linecap': 'round',
    }),
  ])

/** Mic with a slash — the microphone is unavailable or muted. */
export const MicOffIcon: FunctionalComponent<{ size?: number }> = (props) =>
  h('svg', { width: props.size ?? 18, height: props.size ?? 18, viewBox: '0 0 18 18', fill: 'none' }, [
    h('path', {
      d: 'M7 3.5a2 2 0 0 1 4 0v3.2M11 10.2a2 2 0 0 1-4-.5V8',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
    }),
    h('path', {
      d: 'M4 8a5 5 0 0 0 7.4 4.4M14 8v.6M9 13.4V16',
      stroke: 'currentColor',
      'stroke-width': '1.4',
      'stroke-linecap': 'round',
    }),
    h('path', { d: 'M2.6 2.6l12.8 12.8', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round' }),
  ])
