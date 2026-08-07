import { defineStore } from "pinia";
import { ref } from "vue";

export const useGlobalStore = defineStore("global", () => {
  const config = ref({});
  // Set by TemplatePickerModal.vue and consumed by Note.vue's
  // getInitialEditorValue() when creating a note from a template — the two
  // aren't in a parent/child relationship so props can't carry this.
  const pendingTemplate = ref(null);

  return { config, pendingTemplate };
});
