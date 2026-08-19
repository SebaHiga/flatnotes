const STORAGE_KEY = "dashboardColumns";

// Characters with special meaning to Whoosh's query parser. Escaped when
// building a query from a column's selected tags so a tag containing one of
// these doesn't break parsing (tags are normally alphanumeric/-/_, but this
// is cheap insurance).
const QUERY_SPECIAL_CHARS_RE = /(["():\\])/g;

function escapeQueryWord(word) {
  return word.replace(QUERY_SPECIAL_CHARS_RE, "\\$1");
}

/**
 * Builds a Whoosh search term (see server's file_system.py search()) that
 * implements a smart-folder column's tag filter only. Title filtering is
 * done separately (see noteMatchesTitleFilter) directly against each note's
 * raw title, rather than through Whoosh's title: field — Whoosh's analyzer
 * drops short/numeric words (e.g. a lone "4") both when indexing and when
 * parsing a query, so title:4 silently matches nothing and, worse, an AND'd
 * clause built from it gets dropped instead of narrowing the results.
 */
export function buildColumnTagsQuery(column) {
  if (!column.tags?.length) {
    return "*";
  }
  const joiner = column.tagsMatch === "any" ? " OR " : " AND ";
  const tagClauses = column.tags.map((tag) => `tags:${escapeQueryWord(tag)}`);
  return tagClauses.length > 1 ? `(${tagClauses.join(joiner)})` : tagClauses[0];
}

// Regex special characters other than "*", which is treated as a wildcard
// (translated to ".*") rather than escaped.
const REGEXP_SPECIAL_CHARS_RE = /[.+?^${}()|[\]\\]/g;

/**
 * Returns true if `title` matches a column's title-filter pattern. Matching
 * is a literal, case-insensitive substring/glob match against the raw title
 * (with "*" as a wildcard) — not a Whoosh search — so it works reliably for
 * short or numeric words like "4" that Whoosh's index can't find.
 */
export function noteMatchesTitleFilter(title, titleFilter) {
  const trimmed = titleFilter?.trim();
  if (!trimmed) {
    return true;
  }
  const pattern = trimmed
    .split("*")
    .map((part) => part.replace(REGEXP_SPECIAL_CHARS_RE, "\\$&"))
    .join(".*");
  return new RegExp(pattern, "i").test(title);
}

export function newColumn(overrides = {}) {
  return {
    id:
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `col-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: "New Column",
    titleFilter: "",
    tags: [],
    tagsMatch: "all",
    sort: "lastModified",
    order: "desc",
    limit: 10,
    ...overrides,
  };
}

// Per-browser dashboard layout, following the same ad hoc localStorage
// pattern already used for e.g. darkTheme/vimModeEnabled elsewhere in the
// client — there's no user-settings backend to persist this to instead.
export function loadColumns(defaultColumns) {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        return parsed;
      }
    } catch {
      // Fall through and use defaults if the stored value is corrupt.
    }
  }
  return defaultColumns;
}

export function saveColumns(columns) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(columns));
}
