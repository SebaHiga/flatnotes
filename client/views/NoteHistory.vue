<template>
  <!-- Confirm Restore Modal -->
  <ConfirmModal
    v-model="isRestoreModalVisible"
    title="Confirm Restore"
    :message="`Are you sure you want to restore '${title}' to this version? This will overwrite the current content, but the current version will remain in the history.`"
    confirmButtonText="Restore"
    confirmButtonStyle="success"
    @confirm="restoreConfirmedHandler"
  />

  <div class="flex h-full max-w-[900px] flex-col">
    <div class="mb-4 flex items-baseline justify-between">
      <h1 class="truncate text-2xl">History: {{ title }}</h1>
      <RouterLink
        :to="{ name: 'note', params: { title } }"
        class="shrink-0 text-theme-text-muted hover:underline"
        >Back to note</RouterLink
      >
    </div>
    <LoadingIndicator ref="loadingIndicator" class="flex-1 overflow-y-auto">
      <div class="flex h-full flex-col gap-4 md:flex-row">
        <!-- Version List -->
        <div class="shrink-0 overflow-y-auto md:w-64">
          <div
            v-for="entry in entries"
            :key="entry.commitHash"
            class="mb-1 cursor-pointer rounded px-2 py-1 hover:bg-theme-background-elevated"
            :class="{
              'bg-theme-background-elevated':
                selectedEntry?.commitHash === entry.commitHash,
            }"
            @click="selectEntry(entry)"
          >
            <div class="truncate font-medium">{{ changeLabel(entry) }}</div>
            <div class="flex justify-between text-xs text-theme-text-muted">
              <span>{{ entry.timestampAsString }}</span>
              <span class="text-theme-text-very-muted">{{
                entry.commitHash.slice(0, 7)
              }}</span>
            </div>
          </div>
        </div>

        <!-- Detail -->
        <div class="min-w-0 flex-1 overflow-y-auto">
          <template v-if="selectedEntry">
            <LoadingIndicator ref="diffLoadingIndicator">
              <NoteHistoryDiff :diffText="diffText" />
              <CustomButton
                v-if="canModify && selectedEntry.changeType !== 'delete'"
                label="Restore this version"
                :style="'success'"
                class="mt-2"
                @click="restoreHandler(selectedEntry)"
              />
            </LoadingIndicator>
          </template>
          <div v-else class="text-theme-text-muted">
            Select a version to view its changes.
          </div>
        </div>
      </div>
    </LoadingIndicator>
  </div>
</template>

<script setup>
import { mdiHistory } from "@mdi/js";
import { useToast } from "primevue/usetoast";
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";

import {
  apiErrorHandler,
  getNoteHistory,
  getNoteHistoryDiff,
  restoreNoteHistoryVersion,
} from "../api.js";
import ConfirmModal from "../components/ConfirmModal.vue";
import CustomButton from "../components/CustomButton.vue";
import LoadingIndicator from "../components/LoadingIndicator.vue";
import NoteHistoryDiff from "../components/NoteHistoryDiff.vue";
import { authTypes } from "../constants.js";
import { useGlobalStore } from "../globalStore.js";
import { getToastOptions } from "../helpers.js";

const props = defineProps({
  title: String,
});

const diffLoadingIndicator = ref();
const diffText = ref("");
const entries = ref([]);
const globalStore = useGlobalStore();
const isRestoreModalVisible = ref(false);
const loadingIndicator = ref();
const restoreTarget = ref(null);
const router = useRouter();
const selectedEntry = ref(null);
const toast = useToast();

const canModify = computed(
  () => globalStore.config.authType !== authTypes.readOnly,
);

function init() {
  selectedEntry.value = null;
  loadingIndicator.value.setLoading();
  getNoteHistory(props.title)
    .then((data) => {
      entries.value = data;
      if (entries.value.length > 0) {
        loadingIndicator.value.setLoaded();
      } else {
        loadingIndicator.value.setFailed("No History", mdiHistory);
      }
    })
    .catch((error) => {
      loadingIndicator.value.setFailed();
      apiErrorHandler(error, toast);
    });
}

function changeLabel(entry) {
  switch (entry.changeType) {
    case "create":
      return "Created";
    case "rename":
      return `Renamed from '${entry.oldTitle}'`;
    case "delete":
      return "Deleted";
    default:
      return "Updated";
  }
}

async function selectEntry(entry) {
  selectedEntry.value = entry;
  diffText.value = "";
  await nextTick();
  diffLoadingIndicator.value?.setLoading();
  getNoteHistoryDiff(props.title, entry.commitHash)
    .then((data) => {
      diffText.value = data.diff;
      diffLoadingIndicator.value?.setLoaded();
    })
    .catch((error) => {
      diffLoadingIndicator.value?.setFailed();
      apiErrorHandler(error, toast);
    });
}

function restoreHandler(entry) {
  restoreTarget.value = entry;
  isRestoreModalVisible.value = true;
}

function restoreConfirmedHandler() {
  restoreNoteHistoryVersion(props.title, restoreTarget.value.commitHash)
    .then(() => {
      toast.add(getToastOptions("Note restored ✓", "Success", "success"));
      router.push({ name: "note", params: { title: props.title } });
    })
    .catch((error) => {
      apiErrorHandler(error, toast);
    });
}

onMounted(init);
watch(() => props.title, init);
</script>
