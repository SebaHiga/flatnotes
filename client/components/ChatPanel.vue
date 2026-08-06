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
          <p v-if="message.content" class="whitespace-pre-wrap">{{
            message.content
          }}<span v-if="message.streaming" class="animate-pulse"
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
import { nextTick, ref } from "vue";

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

async function send() {
  const askedQuestion = question.value.trim();
  if (!askedQuestion || sending.value) {
    return;
  }
  question.value = "";
  messages.value.push({ role: "user", content: askedQuestion });
  const assistantMessage = {
    role: "assistant",
    content: "",
    edit: null,
    streaming: true,
    error: false,
  };
  messages.value.push(assistantMessage);
  sending.value = true;
  scrollToBottom();
  try {
    await streamChat(askedQuestion, props.noteTitle, (event) => {
      if (event.type === "token") {
        assistantMessage.content += event.content;
      } else if (event.type === "edit") {
        assistantMessage.edit = {
          content: event.content,
          diff: event.diff,
          applying: false,
          resolved: false,
          applied: false,
        };
      } else if (event.type === "error") {
        assistantMessage.error = true;
        assistantMessage.content = event.message;
      }
      scrollToBottom();
    });
  } catch (error) {
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
