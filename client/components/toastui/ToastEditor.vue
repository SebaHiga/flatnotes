<template>
  <div ref="editorElement"></div>
</template>

<script setup>
import Editor from "@toast-ui/editor";
import { onMounted, onUnmounted, ref } from "vue";

import { themeChangeEvent } from "../../constants.js";
import baseOptions from "./baseOptions.js";
import { getFilesFromEvent, isImageFile } from "../../helpers.js";
import { offsetToLineCol } from "../../templatePlaceholders.js";
import { renderMermaidDiagrams, rerenderMermaidDiagrams } from "./mermaid.js";

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

// Positions for the current set of template blanks, computed once up front
// (as [line, col] pairs) rather than tracked live: TOAST UI's public API has
// no way to remap a position through later edits the way CodeMirror does.
// A blank's position can go stale if an earlier edit on the *same* line
// changes its length; blanks on other lines are unaffected.
let blankRanges = [];
let activeBlankIndex = -1;

function renderMermaidHandler() {
  // The markdown-mode preview pane re-renders its HTML asynchronously after
  // a 'load'/'change' event fires, so wait a frame before looking for new
  // `.mermaid` blocks to render.
  requestAnimationFrame(() => renderMermaidDiagrams(editorElement.value));
}

let renderMermaidTimeout;

// Debounced version for the 'change' event, which fires on every keystroke.
// Rendering on each one would fire overlapping mermaid.run() calls against
// diagram text that's still mid-edit (and thus not valid mermaid syntax),
// and each keystroke's preview re-render can yank the DOM nodes out from
// under an in-flight render from the previous keystroke.
function debouncedRenderMermaidHandler() {
  clearTimeout(renderMermaidTimeout);
  renderMermaidTimeout = setTimeout(renderMermaidHandler, 500);
}

function rerenderMermaidHandler() {
  rerenderMermaidDiagrams(editorElement.value);
}

onMounted(() => {
  toastEditor = new Editor({
    ...baseOptions,
    el: editorElement.value,
    initialValue: props.initialValue,
    initialEditType: props.initialEditType,
    events: {
      load: renderMermaidHandler,
      change: () => {
        emit("change");
        debouncedRenderMermaidHandler();
      },
      // Diagrams aren't rendered while the Preview pane is hidden (see
      // mermaid.js), so a render is needed here too for diagrams that were
      // skipped while the Write tab was active.
      changePreviewTabPreview: renderMermaidHandler,
      keydown: (_, event) => {
        emit("keydown", event);
      },
    },
    hooks: props.addImageBlobHook
      ? { addImageBlobHook: props.addImageBlobHook }
      : {},
  });
  window.addEventListener(themeChangeEvent, rerenderMermaidHandler);

  // Intercept paste/drop of non-image files (e.g. PDFs) before TOAST UI's
  // own handling sees them, since TOAST UI's addImageBlobHook only fires
  // for image blobs. Capture phase runs before TOAST UI's listener, which
  // is attached to a descendant node inside this container.
  editorElement.value.addEventListener("paste", interceptFileEvent, true);
  editorElement.value.addEventListener("drop", interceptFileEvent, true);

  // Same capture-phase trick for Tab/Enter: TOAST UI's own ProseMirror
  // keymap handles them internally (e.g. list indentation, new paragraph)
  // regardless of what the `events.keydown` hook above does with it —
  // preventDefault() called from that hook is too late to stop it.
  // Intercepting on this ancestor node in the capture phase runs before
  // ProseMirror's own listener on the descendant editable node sees the
  // event at all.
  editorElement.value.addEventListener("keydown", interceptBlankNavKey, true);
});

onUnmounted(() => {
  clearTimeout(renderMermaidTimeout);
  window.removeEventListener(themeChangeEvent, rerenderMermaidHandler);
});

function interceptBlankNavKey(event) {
  if (activeBlankIndex === -1) {
    return;
  }
  let handled = false;
  if (event.key === "Tab") {
    handled = event.shiftKey ? retreatBlank() : advanceBlank();
  } else if (event.key === "Enter") {
    handled = advanceBlank();
  }
  if (handled) {
    event.preventDefault();
    event.stopPropagation();
  }
}

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

function setMarkdown(content) {
  toastEditor.setMarkdown(content);
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

function focusBlank(index) {
  const [start, end] = blankRanges[index];
  toastEditor.setSelection(start, end);
  toastEditor.focus();
}

function advanceBlank() {
  const next = activeBlankIndex + 1;
  if (next >= blankRanges.length) {
    activeBlankIndex = -1;
    return false;
  }
  activeBlankIndex = next;
  focusBlank(next);
  return true;
}

function retreatBlank() {
  const prev = activeBlankIndex - 1;
  if (prev < 0) {
    activeBlankIndex = -1;
    return false;
  }
  activeBlankIndex = prev;
  focusBlank(prev);
  return true;
}

// blanks: [{ start, end }, ...] character offsets into props.initialValue.
// setSelection only accepts [line, col] positions in markdown edit mode —
// in WYSIWYG mode it expects plain ProseMirror offsets instead, so passing
// these positions there would select the wrong place (or throw). Degrade to
// leaving the cursor wherever TOAST UI put it by default in that mode.
function selectBlanks(blanks) {
  blankRanges = blanks.map(({ start, end }) => [
    offsetToLineCol(props.initialValue, start),
    offsetToLineCol(props.initialValue, end),
  ]);
  if (blankRanges.length === 0 || !toastEditor.isMarkdownMode()) {
    activeBlankIndex = -1;
    return;
  }
  activeBlankIndex = 0;
  focusBlank(0);
}

defineExpose({
  getMarkdown,
  setMarkdown,
  isWysiwygMode,
  insertAttachmentLink,
  insertAttachmentImage,
  insertNewline,
  selectBlanks,
});
</script>

<style>
@import "@toast-ui/editor/dist/toastui-editor.css";
@import "prismjs/themes/prism.css";
@import "@toast-ui/editor-plugin-code-syntax-highlight/dist/toastui-editor-plugin-code-syntax-highlight.css";
@import "./toastui-editor-overrides.scss";
</style>
