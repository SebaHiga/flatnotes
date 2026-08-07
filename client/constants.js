// Params
export const params = {
  searchTerm: "term",
  redirect: "redirect",
  showHighlights: "showHighlights",
  sortBy: "sortBy",
};

export const searchSortOptions = {
  score: 0,
  title: 1,
  lastModified: 2,
};

export const authTypes = {
  none: "none",
  readOnly: "read_only",
  password: "password",
  totp: "totp",
};

export const attachmentUrlPrefix = "attachments/";

// Dispatched on `window` whenever the dark/light theme changes, so
// already-rendered content (e.g. mermaid diagrams) can redraw to match.
export const themeChangeEvent = "flatnotes-theme-change";

// Characters not allowed in a note/attachment title since they're stored as
// {title}.md files on disk (mirrors server/helpers.py's filename validation).
export const reservedFilenameCharacters = /[<>:"/\\|?*]/;
