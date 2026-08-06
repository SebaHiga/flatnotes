<template>
  <div ref="editorElement"></div>
</template>

<script setup>
import Editor from "@toast-ui/editor";
import { onMounted, ref } from "vue";

import baseOptions from "./baseOptions.js";
import { getFilesFromEvent, isImageFile } from "../../helpers.js";

const props = defineProps({
  initialValue: String,
  initialEditType: {
    type: String,
    default: "markdown",
  },
  addImageBlobHook: Function,
});

const emit = defineEmits(["change", "keydown", "fileDrop"]);

const editorElement = ref();
let toastEditor;

onMounted(() => {
  toastEditor = new Editor({
    ...baseOptions,
    el: editorElement.value,
    initialValue: props.initialValue,
    initialEditType: props.initialEditType,
    events: {
      change: () => {
        emit("change");
      },
      keydown: (_, event) => {
        emit("keydown", event);
      },
    },
    hooks: props.addImageBlobHook
      ? { addImageBlobHook: props.addImageBlobHook }
      : {},
  });

  // Intercept paste/drop of non-image files (e.g. PDFs) before TOAST UI's
  // own handling sees them, since TOAST UI's addImageBlobHook only fires
  // for image blobs. Capture phase runs before TOAST UI's listener, which
  // is attached to a descendant node inside this container.
  editorElement.value.addEventListener("paste", interceptFileEvent, true);
  editorElement.value.addEventListener("drop", interceptFileEvent, true);
});

function interceptFileEvent(event) {
  const files = getFilesFromEvent(event);
  if (files.length === 0 || files.every(isImageFile)) {
    // No real files (plain text paste / in-page drag), or an all-image
    // batch: leave the event alone so TOAST UI's own handling (including
    // addImageBlobHook) runs as normal.
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  emit("fileDrop", files);
}

function getMarkdown() {
  return toastEditor.getMarkdown();
}

function isWysiwygMode() {
  return toastEditor.isWysiwygMode();
}

function insertAttachmentLink(text, url) {
  toastEditor.exec("addLink", { linkText: text, linkUrl: url });
}

function insertAttachmentImage(text, url) {
  toastEditor.exec("addImage", { altText: text, imageUrl: url });
}

function insertNewline() {
  toastEditor.insertText("\n");
}

defineExpose({
  getMarkdown,
  isWysiwygMode,
  insertAttachmentLink,
  insertAttachmentImage,
  insertNewline,
});
</script>

<style>
@import "@toast-ui/editor/dist/toastui-editor.css";
@import "prismjs/themes/prism.css";
@import "@toast-ui/editor-plugin-code-syntax-highlight/dist/toastui-editor-plugin-code-syntax-highlight.css";
@import "./toastui-editor-overrides.scss";
</style>
