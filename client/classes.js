import { formatFileSize } from "./helpers.js";
import router from "./router.js";

class Note {
  constructor(note) {
    this.title = note?.title;
    this.lastModified = note?.lastModified;
    this.content = note?.content;
  }

  get lastModifiedAsDate() {
    return new Date(this.lastModified * 1000);
  }

  get lastModifiedAsString() {
    return this.lastModifiedAsDate.toLocaleString();
  }
}

class SearchResult extends Note {
  constructor(searchResult) {
    super(searchResult);
    this.created = searchResult.created;
    this.score = searchResult.score;
    this.titleHighlights = searchResult.titleHighlights;
    this.contentHighlights = searchResult.contentHighlights;
    this.tagMatches = searchResult.tagMatches;
  }

  get createdAsDate() {
    return new Date(this.created * 1000);
  }

  get createdAsString() {
    return this.createdAsDate.toLocaleString();
  }

  get titleHighlightsOrTitle() {
    return this.titleHighlights ? this.titleHighlights : this.title;
  }

  get includesHighlights() {
    if (
      this.titleHighlights ||
      this.contentHighlights ||
      (this.tagMatches != null && this.tagMatches.length)
    ) {
      return true;
    } else {
      return false;
    }
  }
}

class Attachment {
  constructor(attachment) {
    this.filename = attachment?.filename;
    this.url = attachment?.url;
    this.size = attachment?.size;
    this.lastModified = attachment?.lastModified;
    this.notes = attachment?.notes || [];
  }

  get lastModifiedAsDate() {
    return new Date(this.lastModified * 1000);
  }

  get lastModifiedAsString() {
    return this.lastModifiedAsDate.toLocaleString();
  }

  get sizeAsString() {
    return formatFileSize(this.size);
  }
}

class HistoryEntry {
  constructor(entry) {
    this.commitHash = entry?.commitHash;
    this.timestamp = entry?.timestamp;
    this.changeType = entry?.changeType;
    this.title = entry?.title;
    this.oldTitle = entry?.oldTitle;
  }

  get timestampAsDate() {
    return new Date(this.timestamp * 1000);
  }

  get timestampAsString() {
    return this.timestampAsDate.toLocaleString();
  }
}

export { Attachment, HistoryEntry, Note, SearchResult };
