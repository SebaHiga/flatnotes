<template>
  <div class="flex h-full flex-col">
    <div class="mb-2 flex items-center gap-1">
      <select
        v-if="models.length > 1"
        v-model="selectedModel"
        class="w-full truncate rounded border border-theme-border bg-theme-background px-1 py-0.5 text-xs text-theme-text-muted focus:outline-none dark:bg-theme-background-elevated"
      >
        <option v-for="model in models" :key="model.id" :value="model.id">
          {{ model.id }}{{ model.loaded ? "" : " (cold start)"
          }}{{ model.vision ? "" : " — no images" }}
        </option>
      </select>
      <select
        v-model="selectedReasoningEffort"
        class="w-full truncate rounded border border-theme-border bg-theme-background px-1 py-0.5 text-xs text-theme-text-muted focus:outline-none dark:bg-theme-background-elevated"
      >
        <option
          v-for="level in reasoningEffortLevels"
          :key="level.value"
          :value="level.value"
        >
          {{ level.label }}
        </option>
      </select>
    </div>
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
          <!-- Attached Images -->
          <div
            v-if="message.attachments?.length"
            class="mb-1 flex flex-wrap gap-1"
          >
            <img
              v-for="attachment in message.attachments"
              :key="attachment.filename"
              :src="attachment.url"
              :alt="attachment.filename"
              class="h-16 w-16 rounded object-cover"
            />
          </div>

          <!-- Reasoning -->
          <div v-if="message.reasoning" class="mb-1 max-w-full">
            <button
              type="button"
              class="flex max-w-full items-center gap-1 text-left text-xs text-theme-text-muted"
              @click="message.reasoningExpanded = !message.reasoningExpanded"
            >
              <SvgIcon
                type="mdi"
                :path="mdiChevronRight"
                :size="14"
                class="shrink-0 transition-transform"
                :class="{ 'rotate-90': message.reasoningExpanded }"
              ></SvgIcon>
              <span class="min-w-0 flex-1 truncate italic">{{
                message.reasoningExpanded
                  ? "Thinking"
                  : lastReasoningLine(message)
              }}</span>
            </button>
            <p
              v-if="message.reasoningExpanded"
              class="mt-1 whitespace-pre-wrap border-l-2 border-theme-border pl-3 text-xs italic text-theme-text-muted"
            >
              {{ message.reasoning }}
            </p>
          </div>

          <!-- Thinking Indicator -->
          <div
            v-if="message.thinking && !message.reasoning"
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
          <p v-if="!message.thinking" class="whitespace-pre-wrap">
            {{ message.content
            }}<span
              v-if="message.streaming || message.pendingContent"
              class="animate-pulse"
              >▍</span
            >
          </p>

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
          <p
            v-if="message.editError"
            class="mt-2 text-xs text-theme-text-muted"
          >
            {{ message.editError }}
          </p>
          <p v-if="message.notice" class="mt-2 text-xs text-theme-text-muted">
            {{ message.notice }}
          </p>
        </div>
      </div>
    </div>

    <!-- Pending Image Attachments -->
    <div v-if="pendingAttachments.length" class="mb-1 flex flex-wrap gap-1">
      <div
        v-for="(attachment, index) in pendingAttachments"
        :key="attachment.filename"
        class="relative"
      >
        <img
          :src="attachment.url"
          :alt="attachment.filename"
          class="h-12 w-12 rounded object-cover"
        />
        <button
          type="button"
          class="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full border border-theme-border bg-theme-background"
          @click="pendingAttachments.splice(index, 1)"
        >
          <SvgIcon type="mdi" :path="mdiClose" :size="12"></SvgIcon>
        </button>
      </div>
    </div>

    <!-- Input -->
    <div class="flex items-end gap-2">
      <input
        ref="imageInput"
        type="file"
        accept="image/*"
        multiple
        class="hidden"
        @change="fileInputHandler"
      />
      <CustomButton
        :iconPath="mdilPaperclip"
        :disabled="sending"
        @click="imageInput.click()"
      />
      <textarea
        v-model="question"
        v-focus
        rows="1"
        :placeholder="`Ask about '${noteTitle}'...`"
        class="w-full resize-none rounded-md border border-theme-border bg-theme-background px-3 py-2 focus:outline-none dark:bg-theme-background-elevated"
        @keydown.enter.exact.prevent="send"
        @paste="pasteHandler"
      ></textarea>
      <CustomButton
        :iconPath="mdiArrowUp"
        label="Send"
        :style="'cta'"
        :disabled="sending || attaching || !question.trim()"
        @click="send"
      />
    </div>
  </div>
</template>

<script setup>
import SvgIcon from "@jamescoyle/vue-icon";
import { mdiArrowUp, mdiChevronRight, mdiClose } from "@mdi/js";
import { mdilPaperclip } from "@mdi/light-js";
import { useToast } from "primevue/usetoast";
import {
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";

import {
  apiErrorHandler,
  createAttachment,
  getChatModels,
  streamChat,
} from "../api.js";
import { useGlobalStore } from "../globalStore.js";
import { getFilesFromEvent, getToastOptions, isImageFile } from "../helpers.js";
import CustomButton from "./CustomButton.vue";
import NoteHistoryDiff from "./NoteHistoryDiff.vue";

// Mirrors server/chat.py's MAX_IMAGES — attaching more than the server will
// actually forward to the model would just be silently dropped there.
const MAX_CHAT_IMAGES = 4;

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
const models = ref([]);
const selectedModel = ref(localStorage.getItem("chatModel") || "");

// "" is sent to the server as null, meaning "leave the model's own default
// thinking behaviour alone" rather than an explicit level.
const reasoningEffortLevels = [
  { value: "", label: "Default reasoning" },
  { value: "off", label: "No reasoning" },
  { value: "low", label: "Low reasoning" },
  { value: "medium", label: "Medium reasoning" },
  { value: "high", label: "High reasoning" },
  { value: "max", label: "Max reasoning" },
];
const selectedReasoningEffort = ref(
  localStorage.getItem("chatReasoningEffort") || "",
);

const imageInput = ref();
const pendingAttachments = ref([]); // [{filename, url}] — uploaded, not yet sent
const attaching = ref(false);

onMounted(async () => {
  try {
    models.value = await getChatModels();
  } catch (error) {
    // Non-fatal: the send button still works against the server's default
    // model, it's just the picker that won't be available.
    console.error(error);
    return;
  }
  const available = models.value.some(
    (model) => model.id === selectedModel.value,
  );
  if (!available) {
    selectedModel.value =
      models.value.find((model) => model.loaded)?.id ||
      models.value[0]?.id ||
      "";
  }
});

watch(selectedModel, (model) => {
  if (model) {
    localStorage.setItem("chatModel", model);
  }
});

watch(selectedReasoningEffort, (level) => {
  localStorage.setItem("chatReasoningEffort", level);
});

// Builds the {role, content} history sent to the model so it has memory of
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

// Lets a question be asked about an image without first embedding it in
// the note itself — uploaded the same way note attachments are (so the
// server's existing vision pipeline in chat.py just picks it up), but only
// referenced by this one question via chatAttachmentFilenames rather than
// inserted into the note's markdown.
function fileInputHandler(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (files.length > 0) {
    attachImages(files);
  }
}

function pasteHandler(event) {
  const files = getFilesFromEvent(event);
  if (files.length === 0) {
    // No real files (plain text paste): leave the event alone so the
    // textarea's own paste handling runs as normal.
    return;
  }
  event.preventDefault();
  attachImages(files);
}

async function attachImages(files) {
  const images = files.filter(isImageFile);
  if (images.length < files.length) {
    toast.add(
      getToastOptions(
        "Only image files can be attached to a question.",
        "Unsupported file",
        "warn",
      ),
    );
  }
  const room = MAX_CHAT_IMAGES - pendingAttachments.value.length;
  if (room <= 0) {
    toast.add(
      getToastOptions(
        `Only up to ${MAX_CHAT_IMAGES} images can be attached to a question.`,
        "Too many images",
        "warn",
      ),
    );
    return;
  }
  attaching.value = true;
  try {
    await Promise.all(images.slice(0, room).map(uploadImage));
  } finally {
    attaching.value = false;
  }
}

async function uploadImage(file) {
  try {
    const data = await createAttachment(file);
    pendingAttachments.value.push({ filename: data.filename, url: data.url });
  } catch (error) {
    if (error.response?.status === 409) {
      toast.add(
        getToastOptions(
          "An attachment with this filename already exists.",
          "Duplicate",
          "error",
        ),
      );
    } else if (error.response?.status === 413) {
      toast.add(
        getToastOptions(
          `"${file.name}" is too large to upload.`,
          "File too large",
          "error",
        ),
      );
    } else {
      apiErrorHandler(error, toast);
    }
  }
}

async function send() {
  const askedQuestion = question.value.trim();
  if (!askedQuestion || sending.value || attaching.value) {
    return;
  }
  question.value = "";
  const attachments = pendingAttachments.value.splice(0);
  const history = buildHistory();
  messages.value.push({ role: "user", content: askedQuestion, attachments });
  // Reactive so mutations made from the streamChat callback below (holding
  // this same closure reference, not one re-fetched from `messages.value`)
  // actually trigger re-renders — a plain object here would update its
  // fields in memory just fine, but the DOM wouldn't reflect any of it
  // until something unrelated happened to force a re-render.
  const assistantMessage = reactive({
    role: "assistant",
    content: "",
    pendingContent: "",
    reasoning: "",
    reasoningExpanded: false,
    edit: null,
    editError: null,
    notice: null,
    streaming: true,
    thinking: true,
    error: false,
  });
  messages.value.push(assistantMessage);
  sending.value = true;
  scrollToBottom();
  try {
    await streamChat(
      askedQuestion,
      props.noteTitle,
      history,
      selectedModel.value || null,
      selectedReasoningEffort.value || null,
      attachments.map((attachment) => attachment.filename),
      (event) => {
        if (event.type === "token") {
          assistantMessage.thinking = false;
          assistantMessage.pendingContent += event.content;
          startReveal(assistantMessage);
        } else if (event.type === "reasoning") {
          assistantMessage.reasoning += event.content;
        } else if (event.type === "edit") {
          assistantMessage.thinking = false;
          assistantMessage.edit = {
            content: event.content,
            diff: event.diff,
            applying: false,
            resolved: false,
            applied: false,
          };
        } else if (event.type === "edit_error") {
          assistantMessage.thinking = false;
          assistantMessage.editError = event.message;
        } else if (event.type === "notice") {
          assistantMessage.notice = event.message;
        } else if (event.type === "error") {
          stopReveal();
          assistantMessage.thinking = false;
          assistantMessage.pendingContent = "";
          assistantMessage.error = true;
          assistantMessage.content = event.message;
        }
        scrollToBottom();
      },
    );
  } catch (error) {
    stopReveal();
    assistantMessage.thinking = false;
    assistantMessage.pendingContent = "";
    assistantMessage.error = true;
    if (error.response?.status === 503) {
      assistantMessage.content = error.message;
      globalStore.config.chatEnabled = false;
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

// Shows only the most recently streamed line of reasoning text as the
// collapsed preview, so it reads like a live "currently thinking about..."
// status rather than a stale first line.
function lastReasoningLine(message) {
  const lines = message.reasoning.split("\n").filter((line) => line.trim());
  return lines.length ? lines[lines.length - 1] : "";
}

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}
</script>
