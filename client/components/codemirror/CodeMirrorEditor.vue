<template>
  <div ref="editorElement" class="h-full"></div>
</template>

<script setup>
import { markdown } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { vim } from "@replit/codemirror-vim";
import { minimalSetup } from "codemirror";
import { onBeforeUnmount, onMounted, ref } from "vue";

import { getFilesFromEvent } from "../../helpers.js";
import { blankSnippets, startBlankSession } from "./blankSnippets.js";
import { editorExtensions } from "./theme.js";
import { registerVimInstance, unregisterVimInstance } from "./vimCommands.js";

const props = defineProps({
  initialValue: String,
});

// save/saveAndClose/quit are driven by vim's :w / :wq / :x / :q ex-commands.
const emit = defineEmits([
  "change",
  "keydown",
  "fileDrop",
  "save",
  "saveAndClose",
  "quit",
]);

const editorElement = ref();
let view;

onMounted(() => {
  view = new EditorView({
    parent: editorElement.value,
    state: EditorState.create({
      doc: props.initialValue || "",
      extensions: [
        // vim() must come before other keymap extensions so it gets first
        // refusal on every keypress (e.g. Escape, hjkl in normal mode).
        // `status: true` keeps the mode indicator (-- INSERT --, etc.)
        // permanently visible rather than only during `:`/search entry.
        vim({ status: true }),
        minimalSetup,
        markdown({ codeLanguages: languages }),
        EditorView.lineWrapping,
        ...editorExtensions,
        ...blankSnippets,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            emit("change");
          }
        }),
        // Only Ctrl/Cmd+Enter is forwarded upstream (for save). Escape is
        // deliberately not forwarded: vim owns it for insert -> normal mode,
        // and Note.vue's default Escape-closes-editor behaviour would fight
        // the user constantly. Closing/saving is instead done vim-natively
        // via :w / :wq / :q, wired up through registerVimInstance below.
        EditorView.domEventHandlers({
          keydown: (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
              emit("keydown", event);
            }
          },
        }),
      ],
    }),
  });

  registerVimInstance(view, {
    save: () => emit("save"),
    saveAndClose: () => emit("saveAndClose"),
    quit: () => emit("quit"),
  });

  editorElement.value.addEventListener("paste", interceptFileEvent, true);
  editorElement.value.addEventListener("drop", interceptFileEvent, true);
});

onBeforeUnmount(() => {
  if (view) {
    unregisterVimInstance(view);
    view.destroy();
  }
});

function interceptFileEvent(event) {
  const files = getFilesFromEvent(event);
  if (files.length === 0) {
    // No real files (plain text paste / in-page drag): leave the event
    // alone so CodeMirror's own paste/drop handling runs as normal.
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  emit("fileDrop", files);
}

function insertAtCursor(text) {
  const { from, to } = view.state.selection.main;
  view.dispatch({
    changes: { from, to, insert: text },
    selection: { anchor: from + text.length },
  });
  view.focus();
}

function getMarkdown() {
  return view.state.doc.toString();
}

function setMarkdown(content) {
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: content },
  });
}

function isWysiwygMode() {
  return false;
}

function insertAttachmentLink(text, url) {
  insertAtCursor(`[${text}](${url})`);
}

function insertAttachmentImage(text, url) {
  insertAtCursor(`![${text}](${url})`);
}

function insertNewline() {
  insertAtCursor("\n");
}

// blanks: [{ start, end }, ...] character offsets into the doc as it stands
// right after insertion (CodeMirror positions are plain character offsets,
// so these can be used directly with no conversion).
function selectBlanks(blanks) {
  startBlankSession(view, blanks);
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
