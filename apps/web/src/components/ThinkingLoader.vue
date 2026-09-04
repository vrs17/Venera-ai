<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * User-mode in-flight loader. Where the developer view shows the pipeline gate
 * skeleton, the user view shows only this: a single word ("Thinking") with a
 * brand-tinted highlight sweeping through it and three breathing dots. Honest
 * about being busy without exposing any pipeline internals. The ✦ avatar is
 * static so it morphs cleanly into the resolved answer's avatar.
 */
const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <div class="think" role="status" :aria-label="t('thinking')">
    <span class="think__spark" aria-hidden="true">✦</span>
    <span class="think__word">{{ t('thinking') }}</span>
    <span class="think__dots" aria-hidden="true">
      <span class="think__dot" />
      <span class="think__dot" />
      <span class="think__dot" />
    </span>
  </div>
</template>

<style scoped>
.think {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0;
}
.think__spark {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--ink);
  color: var(--ink-contrast);
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.think__word {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.2px;
  /* A bright highlight sweeps left-to-right through the otherwise-muted word. */
  background: linear-gradient(
    100deg,
    var(--text-muted) 0%,
    var(--text-muted) 38%,
    var(--ink) 50%,
    var(--text-muted) 62%,
    var(--text-muted) 100%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: thinkSweep 1.9s ease-in-out infinite;
}
.think__dots {
  display: inline-flex;
  gap: 3px;
  margin-left: -4px;
}
.think__dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--ink);
  animation: thinkPulse 1.4s ease-in-out infinite;
}
.think__dot:nth-child(2) {
  animation-delay: 0.18s;
}
.think__dot:nth-child(3) {
  animation-delay: 0.36s;
}

@keyframes thinkSweep {
  0% {
    background-position: 130% 0;
  }
  100% {
    background-position: -130% 0;
  }
}
@keyframes thinkPulse {
  0%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .think__word {
    animation: none;
    color: var(--text-secondary);
  }
  .think__dot {
    animation: none;
  }
}
</style>
