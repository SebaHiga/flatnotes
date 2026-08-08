<template>
  <div class="flex h-full flex-col">
    <div ref="messageList" class="mb-2 flex-1 overflow-y-auto">
      <p
        v-if="messages.length === 0"
        class="mt-4 text-center text-theme-text-muted"
      >
        Ask a question about "{{ noteTitle }}".
      </p>
      <div
        v-for="(message, index) in messages"
        :key="index"
        class="mb-4 flex"
        :class="{ 'justify-end': message.role === 'user' }"
      >
        <div
          class="max-w-full rounded-md px-3 py-2"
          :class="{
            'bg-theme-background-elevated': message.role === 'user',
            'text-theme-danger': message.error,
          }"
        >
          <!-- Thinking Indicator -->
          <div
            v-if="message.thinking"
            class="flex items-center gap-1 px-1 py-1.5"
          >
            <span
              class="h-1.5 w-1.5 animate-bounce rounded-full bg-theme-text-muted [animation-delay:-300ms]"
            ></span>
            <span
              class="h-1.5 w-1.5 animate-bounce rounded-full bg-theme-text-muted [animation-delay:-150ms]"
            ></span>
            <span
              class="h-1.5 w-1.5 animate-bounce rounded-full bg-theme-text-muted"
            ></span>
          </div>
          <p v-else-if="!message.thinking" class="whitespace-pre-wrap">{{
            message.content
          }}<span
            v-if="message.streaming || message.pendingContent"
            class="animate-pulse"
            >▍</span
          ></p>

          <!-- Proposed Edit -->
          <div v-if="message.edit" class="mt-2 max-w-[420px]">
            <p class="mb-1 text-xs font-bold uppercase text-theme-text-muted">
              Proposed Edit
            </p>
            <NoteHistoryDiff :diffText="message.edit.diff" />
            <div v-if="!message.edit.resolved" class="mt-2 flex gap-1">
              <CustomButton
                label="Apply"
                :style="'success'"
                :disabled="message.edit.applying"
                @click="applyEdit(message)"
              />
              <CustomButton
                label="Discard"
                :style="'danger'"
                :disabled="message.edit.applying"
                @click="message.edit.resolved = true"
              />
            </div>
            <p v-else class="mt-2 text-xs text-theme-text-muted">
              {{ message.edit.applied ? "Applied ✓" : "Discarded" }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="flex items-end gap-2">
      <textarea
        v-model="question"
        v-focus
        rows="1"
        :placeholder="`Ask about '${noteTitle}'...`"
        class="w-full resize-none rounded-md border border-theme-border bg-theme-background px-3 py-2 focus:outline-none dark:bg-theme-background-elevated"
        @keydown.enter.exact.prevent="send"
      ></textarea>
      <CustomButton
        :iconPath="mdiArrowUp"
        label="Send"
        :style="'cta'"
        :disabled="sending || !question.trim()"
        @click="send"
      />
    </div>
  </div>
</template>

<script setup>
import { mdiArrowUp } from "@mdi/js";
import { useToast } from "primevue/usetoast";
import { nextTick, onBeforeUnmount, reactive, ref } from "vue";

import { apiErrorHandler, streamChat } from "../api.js";
import { useGlobalStore } from "../globalStore.js";
import CustomButton from "./CustomButton.vue";
import NoteHistoryDiff from "./NoteHistoryDiff.vue";

const props = defineProps({
  noteTitle: { type: String, required: true },
  // async (newContent) => boolean. Persists a proposed edit and reports
  // back whether it succeeded.
  onApplyEdit: { type: Function, required: true },
});

const globalStore = useGlobalStore();
const toast = useToast();

const question = ref("");
const messages = ref([]);
const messageList = ref();
const sending = ref(false);

// Builds the {role, content} history sent to Ollama so it has memory of
// earlier turns — without this, every message was answered in total
// isolation, so follow-ups like "yes, add it" or "put it under Groceries"
// had nothing to refer back to.
function buildHistory() {
  return messages.value
    .filter((message) => !message.error)
    .map((message) => {
      let content = message.content || "";
      if (message.edit) {
        const status = !message.edit.resolved
          ? "not yet applied"
          : message.edit.applied
            ? "applied by the user"
            : "discarded by the user";
        content += `\n\n[Proposed edit, ${status}, shown to the user as this diff:]\n${message.edit.diff}`;
      }
      return { role: message.role, content };
    });
}

let revealTimer = null;

function stopReveal() {
  if (revealTimer) {
    clearInterval(revealTimer);
    revealTimer = null;
  }
}

// Reveals streamed text a few characters at a time so the reply always
// reads as "typing" in the UI. This matters even though the server already
// streams token-by-token, because a fast local model can finish generating
// a whole reply in well under a second — without pacing it client-side,
// that arrives as one visual jump instead of a stream.
function startReveal(message) {
  if (revealTimer) return;
  revealTimer = setInterval(() => {
    if (!message.pendingContent) {
      if (!message.streaming) {
        stopReveal();
      }
      return;
    }
    const chunkSize = Math.max(
      1,
      Math.ceil(message.pendingContent.length / 20),
    );
    message.content += message.pendingContent.slice(0, chunkSize);
    message.pendingContent = message.pendingContent.slice(chunkSize);
    scrollToBottom();
  }, 20);
}

onBeforeUnmount(stopReveal);

async function send() {
  const askedQuestion = question.value.trim();
  if (!askedQuestion || sending.value) {
    return;
  }
  question.value = "";
  const history = buildHistory();
  messages.value.push({ role: "user", content: askedQuestion });
  // Reactive so mutations made from the streamChat callback below (holding
  // this same closure reference, not one re-fetched from `messages.value`)
  // actually trigger re-renders — a plain object here would update its
  // fields in memory just fine, but the DOM wouldn't reflect any of it
  // until something unrelated happened to force a re-render.
  const assistantMessage = reactive({
    role: "assistant",
    content: "",
    pendingContent: "",
    edit: null,
    streaming: true,
    thinking: true,
    error: false,
  });
  messages.value.push(assistantMessage);
  sending.value = true;
  scrollToBottom();
  try {
    await streamChat(askedQuestion, props.noteTitle, history, (event) => {
      if (event.type === "token") {
        assistantMessage.thinking = false;
        assistantMessage.pendingContent += event.content;
        startReveal(assistantMessage);
      } else if (event.type === "edit") {
        assistantMessage.thinking = false;
        assistantMessage.edit = {
          content: event.content,
          diff: event.diff,
          applying: false,
          resolved: false,
          applied: false,
        };
      } else if (event.type === "error") {
        stopReveal();
        assistantMessage.thinking = false;
        assistantMessage.pendingContent = "";
        assistantMessage.error = true;
        assistantMessage.content = event.message;
      }
      scrollToBottom();
    });
  } catch (error) {
    stopReveal();
    assistantMessage.thinking = false;
    assistantMessage.pendingContent = "";
    assistantMessage.error = true;
    if (error.response?.status === 503) {
      assistantMessage.content = error.message;
      globalStore.config.ollamaEnabled = false;
    } else {
      assistantMessage.content = "Something went wrong.";
      apiErrorHandler(error, toast);
    }
  } finally {
    assistantMessage.streaming = false;
    sending.value = false;
    scrollToBottom();
  }
}

async function applyEdit(message) {
  message.edit.applying = true;
  const success = await props.onApplyEdit(message.edit.content);
  message.edit.applying = false;
  message.edit.resolved = true;
  message.edit.applied = success;
}

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}
</script>
