// Venera UI kutubxonasi (spec §3) - katalog (KitView, hujjat). Ilova kodi komponentni
// FAYLIDAN oladi: `import VButton from '../ui/VButton.vue'`. Sabab: har .vue uslubi
// yon ta'sirli import, ya'ni shu indeks orqali olingan bitta tugma chat bo'lagiga
// admin grafiklari va jadvallarining CSS/JS ini ham tortib kelardi (≈ 50 kB gzip).

// --- tugmalar va maydonlar ---
export { default as VButton } from './VButton.vue'
export { default as VIconButton } from './VIconButton.vue'
export { default as VInput } from './VInput.vue'
export { default as VTextarea } from './VTextarea.vue'
export { default as VSelect } from './VSelect.vue'
export type { SelectOption } from './VSelect.vue'
export { default as VSwitch } from './VSwitch.vue'
export { default as VCheckbox } from './VCheckbox.vue'
export { default as VChoiceChips } from './VChoiceChips.vue'
export type { ChoiceOption } from './VChoiceChips.vue'
export { default as VSegmented } from './VSegmented.vue'
export type { SegmentedOption } from './VSegmented.vue'
export { default as VTabs } from './VTabs.vue'
export type { TabItem } from './VTabs.vue'
export { default as VCopy } from './VCopy.vue'

// --- ko'rsatkichlar ---
export { default as VBadge } from './VBadge.vue'
export { default as VAvatar } from './VAvatar.vue'
export { default as VCard } from './VCard.vue'
export { default as VSkeleton } from './VSkeleton.vue'
export { default as VSpinner } from './VSpinner.vue'
export { default as VEmpty } from './VEmpty.vue'
export { default as VKbd } from './VKbd.vue'
export { default as VDivider } from './VDivider.vue'

// --- overlay'lar ---
export { default as VTooltip } from './VTooltip.vue'
export { default as VPopover } from './VPopover.vue'
export type { PopoverAutoFocus, PopoverFocusContext } from './VPopover.vue'
export { default as VMenu } from './VMenu.vue'
export type { MenuEntry, MenuItemEntry } from './VMenu.vue'
export { default as VMenuItem } from './VMenuItem.vue'
export { default as VDialog } from './VDialog.vue'
export { default as VSheet } from './VSheet.vue'
export type { SheetCloseReason } from './VSheet.vue'
export { default as VResizeHandle } from './VResizeHandle.vue'
export { default as VToastHost } from './VToast.vue'
export { useToast, toast } from './useToast'
export type { ToastOptions, ToastTone, ToastAction, ToastItem } from './useToast'

// --- composable'lar ---
export { useFloating } from './composables/useFloating'
export type { Placement, Side, Align, VirtualElement, FloatingAnchor } from './composables/useFloating'
export { useFocusTrap, useScrollLock, getTabbables } from './composables/useFocusTrap'
export { useLayer, useClickOutside, LAYER_IGNORE_ATTR } from './composables/useClickOutside'
export { useId } from './composables/useId'
export { useMediaQuery, useIsPhone, useCanHover, usePrefersReducedMotion } from './composables/useMediaQuery'
export { useResizablePanel } from './composables/useResizablePanel'
export type { ResizablePanel, ResizablePanelOptions } from './composables/useResizablePanel'

// data & charts
export {
  fmtNumber,
  fmtCompact,
  fmtPercent,
  fmtMs,
  fmtRelative,
  fmtDate,
  fmtDateTime,
  fmtTime,
  toDate,
  toISODate,
  fromISODate,
  startOfDay,
  endOfDay,
  startOfMonth,
  addDays,
  diffDays,
  isSameDay,
  toAppLocale,
  intlLocale,
} from './format'
export type { AppLocale, DateInput, DateOptions, DateTimeStyle, NumberOptions, RelativeOptions } from './format'
export { default as VStat } from './VStat.vue'
export { default as VDataTable } from './VDataTable.vue'
export type { DataTableColumn, SortDir, SortState } from './VDataTable.vue'
export { default as VJson } from './VJson.vue'
export { default as VWaterfall } from './VWaterfall.vue'
export type { WaterfallRow } from './VWaterfall.vue'
export { default as VAreaChart } from './charts/VAreaChart.vue'
export { default as VLineChart } from './charts/VLineChart.vue'
export { default as VBarChart } from './charts/VBarChart.vue'
export { default as VStackedBar } from './charts/VStackedBar.vue'
export { default as VSparkline } from './charts/VSparkline.vue'
export { default as VMeter } from './charts/VMeter.vue'
export { default as VChartLegend } from './charts/VChartLegend.vue'
export { default as VChartTooltip } from './charts/VChartTooltip.vue'
export { default as VChartTable } from './charts/VChartTable.vue'
export type {
  BarDatum,
  ChartSeries,
  ChartTableColumn,
  ChartView,
  ChartX,
  LegendItem,
  StackPart,
  TooltipRow,
  XYChartProps,
} from './charts/scale'

// qidiruv, filtrlar, buyruqlar palitrasi
export { default as VSearchField } from './VSearchField.vue'
export { default as VDateRange, DATE_PRESETS, presetRange, inferPreset, resolveDateRange } from './VDateRange.vue'
export type { DateRangeValue, DatePreset, FixedDatePreset } from './VDateRange.vue'
export { default as VFilterBar, FILTER_BAR_KEY } from './VFilterBar.vue'
export type { FilterBarContext, FilterBarEntry } from './VFilterBar.vue'
export { default as VFilterChip } from './VFilterChip.vue'
export type { FilterOption } from './VFilterChip.vue'
export { default as VCommandPalette } from './VCommandPalette.vue'
export {
  useCommandPalette,
  matchesShortcut,
  ariaShortcut,
  isEditableTarget,
  normalizeSearch,
  scoreCommand,
} from './useCommandPalette'
export type {
  CommandItem,
  CommandGroup,
  CommandProvider,
  CommandProviderOptions,
  CommandProviderResult,
  RecentCommand,
} from './useCommandPalette'
