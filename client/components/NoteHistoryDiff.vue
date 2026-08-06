<template>
  <div
    v-if="lines.length > 0"
    class="overflow-x-auto rounded border border-theme-border font-mono text-sm"
  >
    <div
      v-for="(line, index) in lines"
      :key="index"
      class="whitespace-pre px-2"
      :class="{
        'bg-theme-success/10 text-theme-success': line.type === 'added',
        'bg-theme-danger/10 text-theme-danger': line.type === 'removed',
        'text-theme-text-muted': line.type === 'hunk',
      }"
      >{{ linePrefix(line.type) }}{{ line.content }}</div
    >
  </div>
  <div v-else class="text-theme-text-muted">No content changes.</div>
</template>

<script setup>
import { computed } from "vue";

import { parseUnifiedDiff } from "../helpers.js";

const props = defineProps({
  diffText: String,
});

const lines = computed(() => parseUnifiedDiff(props.diffText));

function linePrefix(type) {
  if (type === "added") return "+ ";
  if (type === "removed") return "- ";
  return "  ";
}
</script>
