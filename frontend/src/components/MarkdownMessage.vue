<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

/**
 * Renders a Markdown answer to sanitized HTML. The answer text is
 * backend-controlled, so we render with raw HTML disabled and then run the
 * output through DOMPurify before injecting it via v-html. The `.md` class
 * carries the global markdown styling (see index.css).
 */
const props = defineProps<{ source: string }>()

// linkify + the default markdown-it preset cover the GFM-ish surface
// (tables, strikethrough, autolinks) the old remark-gfm stack provided.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })

const rendered = computed(() => DOMPurify.sanitize(md.render(props.source)))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="md" v-html="rendered" />
</template>
