<template>
  <div
    class="flex w-72 shrink-0 cursor-grab flex-col rounded-lg border border-theme-border bg-theme-background p-3 active:cursor-grabbing"
  >
    <div class="mb-2 flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-1">
        <SvgIcon
          type="mdi"
          :path="mdiDragVertical"
          class="shrink-0 text-theme-text-very-muted"
        />
        <h3 class="truncate font-bold" :title="column.title">
          {{ column.title }}
        </h3>
      </div>
      <CustomButton
        :iconPath="mdiCog"
        title="Edit column"
        class="shrink-0"
        @click="$emit('edit')"
      />
    </div>
    <LoadingIndicator ref="loadingIndicator" hideLoader class="min-h-16 flex-1">
      <div v-if="notes.length === 0" class="text-sm text-theme-text-very-muted">
        No notes match this filter.
      </div>
      <template v-else>
        <RouterLink
          v-for="note in notes"
          :key="note.title"
          :to="{ name: 'note', params: { title: note.title } }"
          :title="note.title"
          class="mb-1 block truncate rounded px-2 py-1 hover:bg-theme-background-elevated"
        >
          {{ note.title }}
        </RouterLink>
        <RouterLink
          v-if="hasMore"
          :to="{
            name: 'search',
            query: { term: tagsQuery, sortBy: searchSortOptions[column.sort] },
          }"
          class="mt-1 block text-xs text-theme-text-muted hover:underline"
        >
          Show more
        </RouterLink>
      </template>
    </LoadingIndicator>
  </div>
</template>

<script setup>
import SvgIcon from "@jamescoyle/vue-icon";
import { mdiCog, mdiDragVertical } from "@mdi/js";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";

import { apiErrorHandler, getNotes } from "../api.js";
import CustomButton from "../components/CustomButton.vue";
import LoadingIndicator from "../components/LoadingIndicator.vue";
import { searchSortOptions } from "../constants.js";
import {
  buildColumnTagsQuery,
  noteMatchesTitleFilter,
} from "../dashboardColumns.js";

// When a title filter is set, Whoosh can only narrow candidates by tag, so
// a larger batch is fetched and then filtered by title client-side (see
// dashboardColumns.js for why). This caps how many tag-matching notes are
// scanned per column before giving up on finding more title matches.
const TITLE_FILTER_FETCH_LIMIT = 500;

const props = defineProps({ column: { type: Object, required: true } });
defineEmits(["edit"]);

const loadingIndicator = ref();
const notes = ref([]);
const hasMore = ref(false);
const toast = useToast();

const tagsQuery = computed(() => buildColumnTagsQuery(props.column));

function load() {
  const limit = props.column.limit || 10;
  const titleFilter = props.column.titleFilter?.trim();
  loadingIndicator.value?.setLoading();
  getNotes(
    tagsQuery.value,
    props.column.sort || "lastModified",
    props.column.order || "desc",
    titleFilter ? TITLE_FILTER_FETCH_LIMIT : limit + 1,
  )
    .then((data) => {
      const filtered = titleFilter
        ? data.filter((note) => noteMatchesTitleFilter(note.title, titleFilter))
        : data;
      hasMore.value = filtered.length > limit;
      notes.value = filtered.slice(0, limit);
      loadingIndicator.value.setLoaded();
    })
    .catch((error) => {
      loadingIndicator.value.setFailed();
      apiErrorHandler(error, toast);
    });
}

watch(() => props.column, load, { deep: true });
onMounted(load);
</script>
