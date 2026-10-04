<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import DocViewer from '../../components/DocViewer.vue'
import { useDocViewer } from '../../composables/useDocViewer'

/**
 * Iqtibos qilingan hujjat - chatdagi o'sha ko'ruvchi (pdf.js), admin sahifasida.
 *
 * NEGA YANGI VARAQDA EMAS: `/api/v1/chat/doc/<id>` sessiya tokenini SARLAVHADA kutadi
 * (cookie yo'q), oddiy havola 401 qaytarardi. Ko'ruvchi esa faylni token bilan o'zi oladi.
 *
 * Holat chat bilan umumiy (`useDocViewer`): javobdagi `[1]` chipi va "Hujjatni ochish"
 * tugmasi shu holatni ochadi. Sahifadan chiqqanda yopiladi - aks holda keyin ochilgan
 * chatda eski hujjat o'z-o'zidan paydo bo'lardi.
 *
 * Chatda ≥1680px da ko'ruvchi ustun sifatida yonma-yon turadi (joyi chat qatorida). Admin
 * sahifasida bunday qator yo'q - o'sha kenglikda ham o'ngdagi panel bo'lib qoladi.
 */
const { doc, close } = useDocViewer()
onBeforeUnmount(close)
</script>

<template>
  <div v-if="doc" class="adv">
    <DocViewer :doc="doc" @close="close" />
  </div>
</template>

<style scoped>
@media (min-width: 1680px) {
  .adv {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-sheet);
    display: flex;
    justify-content: flex-end;
    width: 480px;
    box-shadow: var(--e3);
  }
}
</style>
