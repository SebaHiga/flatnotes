<template>
  <div ref="viewerElement"></div>
</template>

<script setup>
import Viewer from "@toast-ui/editor/dist/toastui-editor-viewer";
import { onMounted, onUnmounted, ref } from "vue";

import { themeChangeEvent } from "../../constants.js";
import baseOptions from "./baseOptions.js";
import extendedAutolinks from "./extendedAutolinks.js";
import { renderMermaidDiagrams, rerenderMermaidDiagrams } from "./mermaid.js";

const props = defineProps({
  initialValue: String,
});

const viewerElement = ref();

function rerenderMermaidHandler() {
  rerenderMermaidDiagrams(viewerElement.value);
}

onMounted(() => {
  new Viewer({
    ...baseOptions,
    extendedAutolinks,
    el: viewerElement.value,
    initialValue: props.initialValue,
    events: {
      load: () => renderMermaidDiagrams(viewerElement.value),
    },
  });
  window.addEventListener(themeChangeEvent, rerenderMermaidHandler);
});

onUnmounted(() => {
  window.removeEventListener(themeChangeEvent, rerenderMermaidHandler);
});
</script>

<style>
@import "@toast-ui/editor/dist/toastui-editor-viewer.css";
@import "prismjs/themes/prism.css";
@import "@toast-ui/editor-plugin-code-syntax-highlight/dist/toastui-editor-plugin-code-syntax-highlight.css";
@import "./toastui-editor-overrides.scss";
</style>
