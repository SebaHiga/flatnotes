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
        <p
          class="max-w-[85%] whitespace-pre-wrap rounded-md px-3 py-2"
          :class="{
            'bg-theme-background-elevated': message.role === 'user',
            'text-theme-danger': message.error,
          }"
        >
          {{ message.content
          }}<span v-if="message.streaming" class="animate-pulse">▍</span>
        </p>
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

const props = defineProps({
  noteTitle: { type: String, required: true },
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

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}
</script>
