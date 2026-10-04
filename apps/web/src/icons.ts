// Brend belgilari - lucide'da yo'q (unda `apple` - meva), shuning uchun o'zimizniki.
// Qolgan hamma belgi `lucide-vue-next` dan (stroke 1.75). To'ldirilgan logotiplar,
// rangi `currentColor`; `size` - px.

import { h } from 'vue'
import type { FunctionalComponent } from 'vue'

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
