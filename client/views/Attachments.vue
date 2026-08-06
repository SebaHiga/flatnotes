<template>
  <!-- Confirm Deletion Modal -->
  <ConfirmModal
    v-model="isDeleteModalVisible"
    title="Confirm Deletion"
    :message="`Are you sure you want to permanently delete '${attachmentToDelete?.filename}'? This cannot be undone.`"
    confirmButtonText="Delete"
    confirmButtonStyle="danger"
    @confirm="deleteConfirmedHandler"
  />

  <div class="flex h-full max-w-[700px] flex-col">
    <h1 class="mb-4 text-2xl">Attachments</h1>
    <LoadingIndicator ref="loadingIndicator" class="flex-1">
      <div
        v-for="attachment in attachments"
        :key="attachment.filename"
        class="mb-4 rounded px-2 py-1 hover:bg-theme-background-elevated"
      >
        <!-- Filename, Size and Delete Button -->
        <div class="flex items-center justify-between">
          <a
            :href="attachment.url"
            target="_blank"
            rel="noopener"
            class="truncate hover:underline"
            >{{ attachment.filename }}</a
          >
          <div class="flex shrink-0 items-center">
            <span class="ml-2 whitespace-nowrap text-theme-text-muted">{{
              attachment.sizeAsString
            }}</span>
            <CustomButton
              v-if="canModify && attachment.notes.length === 0"
              :iconPath="mdilDelete"
              class="ml-1"
              @click="deleteHandler(attachment)"
            />
          </div>
        </div>
        <!-- Last Modified -->
        <div class="text-theme-text-muted">
          {{ attachment.lastModifiedAsString }}
        </div>
        <!-- Referencing Notes -->
        <div class="mt-1 flex flex-wrap items-center gap-1">
          <RouterLink
            v-for="note in attachment.notes"
            :key="note"
            :to="{ name: 'note', params: { title: note } }"
            class="rounded-full bg-theme-brand px-2 text-xs text-white hover:opacity-80"
            >{{ note }}</RouterLink
          >
          <span
            v-if="attachment.notes.length === 0"
            class="text-xs text-theme-text-very-muted"
            >Not linked to any note</span
          >
        </div>
      </div>
    </LoadingIndicator>
  </div>
</template>

<script setup>
import { mdiPaperclip } from "@mdi/js";
import { mdilDelete } from "@mdi/light-js";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { apiErrorHandler, deleteAttachment, getAttachments } from "../api.js";
import { Attachment } from "../classes.js";
import ConfirmModal from "../components/ConfirmModal.vue";
import CustomButton from "../components/CustomButton.vue";
import LoadingIndicator from "../components/LoadingIndicator.vue";
import { authTypes } from "../constants.js";
import { useGlobalStore } from "../globalStore.js";
import { getToastOptions } from "../helpers.js";

const attachments = ref([]);
const attachmentToDelete = ref(null);
const globalStore = useGlobalStore();
const isDeleteModalVisible = ref(false);
const loadingIndicator = ref();
const toast = useToast();

const canModify = computed(() => {
  return globalStore.config.authType !== authTypes.readOnly;
});

function init() {
  loadingIndicator.value.setLoading();
  getAttachments()
    .then((data) => {
      attachments.value = data.map((attachment) => new Attachment(attachment));
      if (attachments.value.length > 0) {
        loadingIndicator.value.setLoaded();
      } else {
        loadingIndicator.value.setFailed("No Attachments", mdiPaperclip);
      }
    })
    .catch((error) => {
      loadingIndicator.value.setFailed();
      apiErrorHandler(error, toast);
    });
}

function deleteHandler(attachment) {
  attachmentToDelete.value = attachment;
  isDeleteModalVisible.value = true;
}

function deleteConfirmedHandler() {
  const attachment = attachmentToDelete.value;
  deleteAttachment(attachment.filename)
    .then(() => {
      attachments.value = attachments.value.filter(
        (candidate) => candidate.filename !== attachment.filename,
      );
      toast.add(getToastOptions("Attachment deleted ✓", "Success", "success"));
      if (attachments.value.length === 0) {
        loadingIndicator.value.setFailed("No Attachments", mdiPaperclip);
      }
    })
    .catch((error) => {
      if (error.response?.status === 409) {
        toast.add(
          getToastOptions(
            "This attachment is still linked to a note.",
            "Cannot Delete",
            "error",
          ),
        );
      } else {
        apiErrorHandler(error, toast);
      }
    });
}

onMounted(init);
</script>
