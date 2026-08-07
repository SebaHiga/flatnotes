import * as constants from "./constants.js";

import { HistoryEntry, Note, SearchResult } from "./classes.js";

import axios from "axios";
import { getStoredToken } from "./tokenStorage.js";
import { getToastOptions } from "./helpers.js";
import router from "./router.js";

const api = axios.create();

api.interceptors.request.use(
  // If the request is not for the token endpoint, add the token to the headers.
  function (config) {
    if (config.url !== "api/token") {
      const token = getStoredToken();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
    return config;
  },
  function (error) {
    return Promise.reject(error);
  },
);

export function apiErrorHandler(error, toast) {
  if (error.response?.status === 401) {
    const redirectPath = router.currentRoute.value.fullPath;
    router.push({
      name: "login",
      query: { [constants.params.redirect]: redirectPath },
    });
  } else {
    console.error(error);
    toast.add(
      getToastOptions(
        "Unknown error communicating with the server. Please try again.",
        "Unknown Error",
        "error",
      ),
    );
  }
}

export async function getConfig() {
  try {
    const response = await api.get("api/config");
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getToken(username, password, totp) {
  try {
    const response = await api.post("api/token", {
      username: username,
      password: totp ? password + totp : password,
    });
    return response.data.access_token;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function authCheck() {
  try {
    const response = await api.get("api/auth-check");
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getNotes(term, sort, order, limit) {
  try {
    const response = await api.get("api/search", {
      params: {
        term: term,
        sort: sort,
        order: order,
        limit: limit,
      },
    });
    return response.data.map((note) => new SearchResult(note));
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function createNote(title, content) {
  try {
    const response = await api.post("api/notes", {
      title: title,
      content: content,
    });
    return new Note(response.data);
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getNote(title) {
  try {
    const response = await api.get(`api/notes/${encodeURIComponent(title)}`);
    return new Note(response.data);
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function updateNote(title, newTitle, newContent) {
  try {
    const response = await api.patch(`api/notes/${encodeURIComponent(title)}`, {
      newTitle: newTitle,
      newContent: newContent,
    });
    return new Note(response.data);
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function deleteNote(title) {
  try {
    await api.delete(`api/notes/${encodeURIComponent(title)}`);
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getNoteHistory(title) {
  try {
    const response = await api.get(
      `api/notes/${encodeURIComponent(title)}/history`,
    );
    return response.data.map((entry) => new HistoryEntry(entry));
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getNoteHistoryVersion(title, commitHash) {
  try {
    const response = await api.get(
      `api/notes/${encodeURIComponent(title)}/history/${encodeURIComponent(commitHash)}`,
    );
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getNoteHistoryDiff(title, commitHash) {
  try {
    const response = await api.get(
      `api/notes/${encodeURIComponent(title)}/history/${encodeURIComponent(commitHash)}/diff`,
    );
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function restoreNoteHistoryVersion(title, commitHash) {
  try {
    const response = await api.post(
      `api/notes/${encodeURIComponent(title)}/history/${encodeURIComponent(commitHash)}/restore`,
    );
    return new Note(response.data);
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getTags() {
  try {
    const response = await api.get("api/tags");
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function getAttachments() {
  try {
    const response = await api.get("api/attachments");
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function deleteAttachment(filename) {
  try {
    await api.delete(`api/attachments/${encodeURIComponent(filename)}`);
  } catch (response) {
    return Promise.reject(response);
  }
}

export async function streamChat(question, noteTitle, history, onEvent) {
  // Uses raw fetch rather than the axios instance above because axios
  // (1.19.0) doesn't expose a readable stream for the response body.
  const url = new URL("api/chat", document.baseURI);
  const headers = { "Content-Type": "application/json" };
  const token = getStoredToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(url, {
    method: "POST",
    headers: headers,
    body: JSON.stringify({
      question: question,
      noteTitle: noteTitle,
      history: history,
    }),
  });
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = null;
    }
    const error = new Error(detail || "Failed to reach the server.");
    error.response = response;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (line.trim()) {
        onEvent(JSON.parse(line));
      }
    }
  }
  if (buffer.trim()) {
    onEvent(JSON.parse(buffer));
  }
}

export async function createAttachment(file, onProgress) {
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post("api/attachments", formData, {
      // Note: no explicit Content-Type header here — the browser needs to
      // set multipart/form-data itself so it can include the boundary
      // parameter. A hardcoded header without one makes the server unable
      // to parse the body ("Missing boundary in multipart").
      onUploadProgress: onProgress
        ? (event) => onProgress(event.loaded, event.total)
        : undefined,
    });
    return response.data;
  } catch (response) {
    return Promise.reject(response);
  }
}
