<template>
  <!-- Add/Edit Column Modal -->
  <DashboardColumnEditModal
    v-model="isEditModalVisible"
    :column="editingColumn"
    :isNew="isNewColumn"
    @save="saveColumn"
    @delete="deleteColumn"
  />

  <div class="flex h-full flex-col overflow-hidden">
    <!-- Top Bar -->
    <div class="mb-4 flex shrink-0 items-center gap-4">
      <Logo responsive />
      <SearchInput class="max-w-[500px] flex-1" />
    </div>

    <!-- Dashboard -->
    <div class="flex min-h-0 flex-1 flex-col">
      <div class="mb-3 flex shrink-0 items-center justify-between">
        <h2 class="text-xs font-bold uppercase text-theme-text-very-muted">
          Dashboard
        </h2>
        <CustomButton
          label="Add Column"
          :iconPath="mdiPlus"
          @click="addColumn"
        />
      </div>
      <div
        v-if="columns.length === 0"
        class="text-sm text-theme-text-very-muted"
      >
        No columns yet. Click "Add Column" to build your dashboard.
      </div>
      <div
        v-else
        class="flex min-h-0 flex-1 flex-wrap content-start gap-4 overflow-y-auto pb-2"
      >
        <DashboardColumn
          v-for="(column, index) in columns"
          :key="column.id"
          :column="column"
          draggable="true"
          class="transition-opacity"
          :class="{ 'opacity-40': draggedIndex === index }"
          @edit="editColumn(column)"
          @dragstart="dragStartHandler(index, $event)"
          @dragover.prevent="dragOverHandler(index)"
          @drop.prevent
          @dragend="dragEndHandler"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { mdiPlus } from "@mdi/js";
import { ref } from "vue";

import CustomButton from "../components/CustomButton.vue";
import Logo from "../components/Logo.vue";
import { loadColumns, newColumn, saveColumns } from "../dashboardColumns.js";
import DashboardColumn from "../partials/DashboardColumn.vue";
import DashboardColumnEditModal from "../partials/DashboardColumnEditModal.vue";
import SearchInput from "../partials/SearchInput.vue";

// Dashboard columns

const columns = ref(loadColumns([newColumn({ title: "Recent" })]));
const editingColumn = ref(newColumn());
const isNewColumn = ref(false);
const isEditModalVisible = ref(false);
const draggedIndex = ref(null);

function persistColumns() {
  saveColumns(columns.value);
}

function dragStartHandler(index, event) {
  draggedIndex.value = index;
  event.dataTransfer.effectAllowed = "move";
  // Required by Firefox for the drag to start at all.
  event.dataTransfer.setData("text/plain", "");
}

// Reorders live as the dragged column passes over another, rather than only
// on drop, so the layout previews the new order while dragging.
function dragOverHandler(index) {
  if (draggedIndex.value === null || draggedIndex.value === index) {
    return;
  }
  const reordered = [...columns.value];
  const [moved] = reordered.splice(draggedIndex.value, 1);
  reordered.splice(index, 0, moved);
  columns.value = reordered;
  draggedIndex.value = index;
}

function dragEndHandler() {
  draggedIndex.value = null;
  persistColumns();
}

function addColumn() {
  editingColumn.value = newColumn();
  isNewColumn.value = true;
  isEditModalVisible.value = true;
}

function editColumn(column) {
  editingColumn.value = column;
  isNewColumn.value = false;
  isEditModalVisible.value = true;
}

function saveColumn(updated) {
  const index = columns.value.findIndex((column) => column.id === updated.id);
  if (index === -1) {
    columns.value.push(updated);
  } else {
    columns.value[index] = updated;
  }
  persistColumns();
}

function deleteColumn(id) {
  columns.value = columns.value.filter((column) => column.id !== id);
  persistColumns();
}
</script>
