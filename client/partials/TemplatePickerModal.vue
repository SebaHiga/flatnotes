<template>
  <Modal v-model="isVisible" class="max-h-[70vh] overflow-y-auto p-4">
    <h2 class="mb-2 text-lg">New Note From Template</h2>
    <div v-if="templates.length === 0" class="text-theme-text-muted">
      No templates yet. Tag any note <code>#{{ TEMPLATE_TAG }}</code> to make
      it one.
    </div>
    <div
      v-for="template in templates"
      :key="template.title"
      class="cursor-pointer truncate rounded px-2 py-1 hover:bg-theme-background-elevated"
      @click="selectTemplate(template)"
    >
      {{ template.title }}
    </div>
  </Modal>
</template>

<script setup>
import { useToast } from "primevue/usetoast";
import { ref, watch } from "vue";
import { useRouter } from "vue-router";

import { apiErrorHandler, getNote, getNotes } from "../api.js";
import Modal from "../components/Modal.vue";
import { useGlobalStore } from "../globalStore.js";
import { getToastOptions } from "../helpers.js";
import {
  TEMPLATE_TAG,
  buildNoteFromTemplate,
} from "../templatePlaceholders.js";

const isVisible = defineModel({ type: Boolean });
const globalStore = useGlobalStore();
const router = useRouter();
const toast = useToast();

const templates = ref([]);

watch(isVisible, (visible) => {
  if (visible) {
    loadTemplates();
  }
});

function loadTemplates() {
  getNotes(`#${TEMPLATE_TAG}`, "title", "asc")
    .then((data) => {
      templates.value = data;
    })
    .catch((error) => {
      apiErrorHandler(error, toast);
    });
}

function selectTemplate(template) {
  getNote(template.title)
    .then((note) => {
      globalStore.pendingTemplate = buildNoteFromTemplate(note.content);
      isVisible.value = false;
      router.push({ name: "new" });
    })
    .catch((error) => {
      apiErrorHandler(error, toast);
    });
}
</script>
