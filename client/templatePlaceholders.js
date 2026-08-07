// Templates are just regular notes tagged #template (server/notes/file_system
// file_system.py's TAGS_WITH_HASH_RE convention: a #word preceded by start-of-
// string/whitespace and followed by whitespace/end-of-string). Everything
// below is pure, client-side substitution — the server never sees {{...}}
// syntax for a note created from a template.

import { reservedFilenameCharacters } from "./constants.js";

export const TEMPLATE_TAG = "template";

const TEMPLATE_TAG_RE = new RegExp(
  `(?:(?<=^)|(?<=\\s))#${TEMPLATE_TAG}(?=\\s|$)`,
  "gim",
);

// A directive line (anywhere in the template) that sets the title of notes
// created from it, e.g. "#title: {{date}} - {{blank:Client name}}". Not a
// real tag: server/notes/file_system/file_system.py's tag regex requires a
// #word to be immediately followed by whitespace/end-of-string, and the
// colon here breaks that match, so this is never indexed as a "title" tag.
const TITLE_DIRECTIVE_RE = /^#title:[ \t]*(.*)$/im;

const DATE_TIME_RE = /\{\{\s*(date|time|datetime)\s*\}\}/g;

// {{blank}}, {{blank:Label text}}, {{cursor}} (alias for an unlabelled
// blank) and {{cursor:Label text}}.
const BLANK_RE = /\{\{\s*(?:blank|cursor)(?::([^}]*))?\s*\}\}/g;

const RESERVED_FILENAME_CHARACTERS_GLOBAL_RE = new RegExp(
  reservedFilenameCharacters.source,
  "g",
);

function tidyWhitespace(content) {
  return content
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\n+/, "")
    .trimEnd();
}

// Remove the #template tag itself so a note created from a template doesn't
// itself get picked up as a template later, then tidy up the whitespace it
// leaves behind.
export function stripTemplateTag(content) {
  return tidyWhitespace(content.replace(TEMPLATE_TAG_RE, ""));
}

// Pulls the "#title: ..." directive (if any) out of the template content,
// returning its raw (not yet substituted) value and the content with that
// line removed. Whitespace cleanup is left to the caller — it also has to
// clean up after stripTemplateTag(), and doing it once at the end avoids
// shifting offsets extractBlanks() hasn't computed yet.
export function extractTitleDirective(content) {
  const match = TITLE_DIRECTIVE_RE.exec(content);
  if (!match) {
    return { titleTemplate: "", content };
  }
  return {
    titleTemplate: match[1].trim(),
    content:
      content.slice(0, match.index) +
      content.slice(match.index + match[0].length),
  };
}

export function substituteDatePlaceholders(content) {
  const now = new Date();
  const replacements = {
    date: now.toLocaleDateString(),
    time: now.toLocaleTimeString(),
    datetime: now.toLocaleString(),
  };
  return content.replace(DATE_TIME_RE, (_, token) => replacements[token]);
}

// Replaces each {{blank}}/{{blank:Label}}/{{cursor}} token with its label
// (or empty string) and returns the resulting plain-text content alongside
// an ordered list of {start, end} character-offset ranges — one per blank,
// tracked against the *output* string since earlier replacements shift the
// positions of everything after them.
export function extractBlanks(content) {
  let result = "";
  let lastIndex = 0;
  const blanks = [];
  let match;
  BLANK_RE.lastIndex = 0;
  while ((match = BLANK_RE.exec(content)) !== null) {
    result += content.slice(lastIndex, match.index);
    const label = match[1] ?? "";
    const start = result.length;
    result += label;
    blanks.push({ start, end: result.length });
    lastIndex = BLANK_RE.lastIndex;
  }
  result += content.slice(lastIndex);
  return { content: result, blanks };
}

// Resolves a title template ({{date}}, {{blank:Label}}, etc.) down to plain
// text and makes it safe to use as a note title: notes are stored as
// {title}.md files, so any placeholder that can produce a character like
// "/" (e.g. a locale date format) would otherwise silently break saving. A
// title template's blanks are resolved to their label text directly rather
// than kept as tab-stops — the title is a plain <input>, not one of the
// tab-stop-capable content editors.
export function resolveTitleTemplate(titleTemplate) {
  const resolved = extractBlanks(
    substituteDatePlaceholders(titleTemplate),
  ).content;
  return resolved.replace(RESERVED_FILENAME_CHARACTERS_GLOBAL_RE, "-").trim();
}

// Converts a character offset into a 1-based [line, col] pair, matching
// TOAST UI's MdPos convention.
export function offsetToLineCol(content, offset) {
  let line = 1;
  let col = 1;
  for (let i = 0; i < offset; i++) {
    if (content[i] === "\n") {
      line++;
      col = 1;
    } else {
      col++;
    }
  }
  return [line, col];
}

export function buildNoteFromTemplate(rawContent) {
  const { titleTemplate, content: withoutTitleDirective } =
    extractTitleDirective(rawContent);
  const content = substituteDatePlaceholders(
    stripTemplateTag(withoutTitleDirective),
  );
  const title = resolveTitleTemplate(titleTemplate);
  return { title, ...extractBlanks(content) };
}
