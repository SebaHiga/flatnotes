<template>
  <Modal
    v-model="isVisible"
    class="max-h-[85vh] w-full max-w-[420px] overflow-y-auto p-4"
  >
    <h2 class="mb-4 text-lg">{{ isNew ? "New Column" : "Edit Column" }}</h2>

    <!-- Title -->
    <label
      class="mb-1 block text-xs font-bold uppercase text-theme-text-very-muted"
      >Title</label
    >
    <TextInput v-model="form.title" class="mb-3" />

    <!-- Title Filter -->
    <label
      class="mb-1 block text-xs font-bold uppercase text-theme-text-very-muted"
      >Title Filter</label
    >
    <TextInput
      v-model="form.titleFilter"
      placeholder="e.g. Laboratorio 4*"
      class="mb-1"
    />
    <p class="mb-3 text-xs text-theme-text-muted">
      Only show notes whose title contains this text. Use <code>*</code> as a
      wildcard (e.g. <code>Laboratorio 4*</code>). Leave blank to match any
      title.
    </p>

    <!-- Tags -->
    <label
      class="mb-1 block text-xs font-bold uppercase text-theme-text-very-muted"
      >Tags</label
    >
    <div
      v-if="allTags.length === 0"
      class="mb-3 text-sm text-theme-text-very-muted"
    >
      No tags yet.
    </div>
    <div v-else class="mb-1 flex flex-wrap gap-1">
      <button
        v-for="tag in allTags"
        :key="tag"
        type="button"
        class="rounded-full px-2 text-xs"
        :class="
          form.tags.includes(tag)
            ? 'bg-theme-brand text-white'
            : 'hover:text-theme-text-normal bg-theme-background-elevated text-theme-text-muted'
        "
        @click="toggleTag(tag)"
      >
        #{{ tag }}
      </button>
    </div>
    <div
      v-if="form.tags.length > 1"
      class="mb-3 mt-1 flex items-center gap-2 text-xs text-theme-text-muted"
    >
      Match:
      <button
        type="button"
        :class="{ underline: form.tagsMatch === 'all' }"
        @click="form.tagsMatch = 'all'"
      >
        All tags
      </button>
      <button
        type="button"
        :class="{ underline: form.tagsMatch === 'any' }"
        @click="form.tagsMatch = 'any'"
      >
        Any tag
      </button>
    </div>
    <div v-else class="mb-3"></div>

    <!-- Sort By -->
    <label
      class="mb-1 block text-xs font-bold uppercase text-theme-text-very-muted"
      >Sort By</label
    >
    <div class="mb-3 flex gap-2">
      <CustomButton
        label="Last Modified"
        :style="form.sort === 'lastModified' ? 'cta' : 'subtle'"
        @click="form.sort = 'lastModified'"
      />
      <CustomButton
        label="Title"
        :style="form.sort === 'title' ? 'cta' : 'subtle'"
        @click="form.sort = 'title'"
      />
      <CustomButton
        label="Created"
        :style="form.sort === 'created' ? 'cta' : 'subtle'"
        @click="form.sort = 'created'"
      />
    </div>

    <!-- Order -->
    <label
      class="mb-1 block text-xs font-bold uppercase text-theme-text-very-muted"
      >Order</label
    >
    <div class="mb-3">
      <CustomButton
        :label="form.order === 'asc' ? 'Ascending' : 'Descending'"
        @click="form.order = form.order === 'asc' ? 'desc' : 'asc'"
      />
    </div>

    <!-- Limit -->
    <label
      class="mb-1 block text-xs font-bold uppercase text-theme-text-very-muted"
      >Max Notes Shown</label
    >
    <input
      v-model.number="form.limit"
      type="number"
      min="1"
      max="50"
      class="mb-4 w-20 rounded-md border border-theme-border bg-transparent px-3 py-2 focus:outline-none dark:bg-theme-background-elevated"
    />

    <!-- Buttons -->
    <div class="flex items-center justify-end gap-2">
      <CustomButton
        v-if="!isNew"
        label="Delete"
        style="danger"
        class="mr-auto"
        @click="deleteHandler"
      />
      <CustomButton label="Cancel" @click="cancelHandler" />
      <CustomButton label="Save" style="cta" @click="saveHandler" />
    </div>
  </Modal>
</template>

<script setup>
import { useToast } from "primevue/usetoast";
import { reactive, ref, watch } from "vue";

import { apiErrorHandler, getTags } from "../api.js";
import CustomButton from "../components/CustomButton.vue";
import Modal from "../components/Modal.vue";
import TextInput from "../components/TextInput.vue";
import { getToastOptions } from "../helpers.js";

const props = defineProps({
  column: { type: Object, required: true },
  isNew: { type: Boolean, default: false },
});
const emit = defineEmits(["save", "delete"]);
const isVisible = defineModel({ type: Boolean });
const toast = useToast();

const allTags = ref([]);
const form = reactive(cloneColumn(props.column));

function cloneColumn(column) {
  return { ...column, tags: [...(column.tags || [])] };
}

// Re-sync the edit form and refresh the tag list each time the modal is
// opened, since `column` may be a different column (or the same one edited
// again after tags changed elsewhere) since it was last shown.
watch(isVisible, (visible) => {
  if (visible) {
    Object.assign(form, cloneColumn(props.column));
    loadTags();
  }
});

function loadTags() {
  getTags()
    .then((data) => {
      allTags.value = data;
    })
    .catch((error) => apiErrorHandler(error, toast));
}

function toggleTag(tag) {
  const index = form.tags.indexOf(tag);
  if (index === -1) {
    form.tags.push(tag);
  } else {
    form.tags.splice(index, 1);
  }
  if (form.tags.length <= 1) {
    form.tagsMatch = "all";
  }
}

function saveHandler() {
  if (!form.title.trim()) {
    toast.add(
      getToastOptions("Please enter a column title.", "Error", "error"),
    );
    return;
  }
  emit("save", cloneColumn(form));
  isVisible.value = false;
}

function cancelHandler() {
  isVisible.value = false;
}

function deleteHandler() {
  emit("delete", form.id);
  isVisible.value = false;
}
</script>
