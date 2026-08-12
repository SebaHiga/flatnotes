import base64
import difflib
import json
import os
from typing import AsyncIterator, List, Literal, Optional

import httpx
import pypdf

import api_messages
from helpers import CustomBaseModel, get_env
from logger import logger
from notes.models import Note

MAX_HISTORY_MESSAGES = 20

MAX_NOTE_CONTENT_CHARS = 6000
MAX_ATTACHMENT_TEXT_CHARS = 4000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4

IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log", ".py", ".js",
    ".ts", ".html", ".css", ".xml", ".ini", ".toml", ".sh",
}

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant answering questions \
and making edits for the user's note titled "{title}".

The note's exact current content is reproduced below between the \
-----BEGIN NOTE----- and -----END NOTE----- markers, and nowhere else in \
this prompt. Only use the information between those markers (and any \
attached files described further below) to answer questions. If it \
doesn't contain the answer, say so honestly rather than guessing.

-----BEGIN NOTE-----
{content}
-----END NOTE-----"""

EDIT_NOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_note",
        "description": (
            "Propose a change to the note by giving the exact existing "
            "text to find and what to replace it with. Never retype or "
            "regenerate the whole note — only the small snippet that's "
            "actually changing; everything else is preserved "
            "automatically. Call this whenever the user wants the note "
            "changed in any way — asked outright ('add a section about "
            "X', 'fix the date') or more casually ('can you note down...', "
            "'that heading should say...', 'yes, go ahead'). If a request "
            "could reasonably be read as wanting the note updated, call "
            "this tool rather than just describing the change in words — "
            "the user always sees a diff and must explicitly approve it "
            "before anything is saved, so proposing an edit is low-risk. "
            "Only skip it for pure questions ('what does this say about "
            "X') that don't ask for any change. To make several separate "
            "changes, call this tool once per change. To move existing "
            "content to a different place in the note, use two calls: one "
            "with `replace` empty to remove it from its old spot, and "
            "another to insert it at the new spot — a single call can "
            "only change text in place, not relocate it, so skipping the "
            "removal call would leave it duplicated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "find": {
                    "type": "string",
                    "description": (
                        "A short snippet — a few words up to a couple of "
                        "lines — copied EXACTLY, character-for-character, "
                        "from the note's current content (between "
                        "-----BEGIN NOTE----- and -----END NOTE----- in "
                        "the system prompt). It must match the note's text "
                        "exactly and appear only once — pick something "
                        "specific enough for that, such as a whole line or "
                        "list item, rather than a single common word. "
                        "Everything in the note other than this snippet is "
                        "left completely untouched. To add something new "
                        "at the very end of the note without changing any "
                        "existing text, set this to an empty string "
                        "instead."
                    ),
                },
                "replace": {
                    "type": "string",
                    "description": (
                        "The text that replaces `find`. To insert "
                        "something next to existing text rather than "
                        "delete it, repeat that text here plus the "
                        "addition — e.g. set `find` to one list item and "
                        "`replace` to that same item followed by a new "
                        "line for the new item, so the original is kept. "
                        "If `find` was empty, this is appended as a new "
                        "paragraph at the end of the note instead."
                    ),
                },
            },
            "required": ["find", "replace"],
        },
    },
}


class ChatMessage(CustomBaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(CustomBaseModel):
    question: str
    note_title: str
    history: List[ChatMessage] = []
    # Overrides the server's default FLATNOTES_LLAMACPP_MODEL for this
    # request, letting the user pick from whatever's listed by list_models().
    model: Optional[str] = None


class ChatModelInfo(CustomBaseModel):
    id: str
    loaded: bool
    vision: bool


class LlamaCppUnavailableError(Exception):
    pass


def _event(event_type: str, **fields) -> bytes:
    return (json.dumps({"type": event_type, **fields}) + "\n").encode()


def _attachments_dir() -> str:
    return os.path.join(get_env("FLATNOTES_PATH", mandatory=True), "attachments")


def _extract_pdf_text(path: str) -> str:
    try:
        reader = pypdf.PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        logger.warning(f"Failed to extract text from PDF '{path}'", exc_info=True)
        return ""


def _load_attachments(filenames: List[str]):
    """Split the given attachment filenames into (images, text_block).
    Images are returned as (mime_type, base64_str) tuples, ready to embed
    as data URIs for vision-capable models; text files and PDFs (text
    extracted via pypdf) are concatenated into a single text block.
    Missing, oversized, or unsupported files are silently skipped."""
    images = []
    text_parts = []
    attachments_dir = _attachments_dir()
    for filename in filenames:
        path = os.path.join(attachments_dir, filename)
        ext = os.path.splitext(filename)[1].lower()
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if ext in IMAGE_MIME_TYPES:
            if len(images) >= MAX_IMAGES or size > MAX_IMAGE_BYTES:
                continue
            with open(path, "rb") as f:
                images.append((IMAGE_MIME_TYPES[ext], base64.b64encode(f.read()).decode()))
        elif ext in TEXT_ATTACHMENT_EXTENSIONS:
            with open(path, "r", errors="replace") as f:
                content = f.read(MAX_ATTACHMENT_TEXT_CHARS + 1)
            if len(content) > MAX_ATTACHMENT_TEXT_CHARS:
                content = content[:MAX_ATTACHMENT_TEXT_CHARS] + "\n...(truncated)"
            text_parts.append(f"### Attachment: {filename}\n{content}")
        elif ext == ".pdf":
            content = _extract_pdf_text(path).strip()
            if not content:
                continue
            if len(content) > MAX_ATTACHMENT_TEXT_CHARS:
                content = content[:MAX_ATTACHMENT_TEXT_CHARS] + "\n...(truncated)"
            text_parts.append(f"### Attachment: {filename}\n{content}")
    return images, "\n\n".join(text_parts)


def _unescape_stray_newlines(text: str) -> str:
    """Small models occasionally emit a literal backslash-n (two chars)
    instead of an actual line break inside tool-call string arguments —
    likely a JSON-escaping artifact, since any '\\n' surviving our
    json.loads() of the arguments was written by the model as a literal
    two-character sequence rather than a real newline. Markdown notes
    essentially never contain a genuine literal backslash-n, so
    unescaping it is safe."""
    return text.replace("\\n", "\n").replace("\\t", "\t")


def _apply_edit(content: str, find: str, replace: str):
    """Applies a single find/replace edit to note content. Returns
    (new_content, None) on success, or (None, error_message) if `find`
    doesn't match exactly one place in `content`. An empty `find` means
    "append at the end" rather than a failed match, since asking a small
    model to precisely re-quote the note's trailing text is unreliable."""
    if find == "":
        base = content.rstrip("\n")
        return (base + "\n\n" + replace if base else replace), None
    count = content.count(find)
    if count == 0:
        return None, "text not found in note"
    if count > 1:
        return None, "text is not unique in note"
    return content.replace(find, replace, 1), None


def _unified_diff(old_content: str, new_content: str) -> str:
    diff_lines = difflib.unified_diff(
        (old_content or "").splitlines(),
        (new_content or "").splitlines(),
        lineterm="",
    )
    return "\n".join(diff_lines)


async def list_models(host: str) -> List[ChatModelInfo]:
    """Query llama.cpp's /v1/models for the presets it knows about, so the
    user can pick which one to chat with. Presets are configured on the
    llama.cpp side (e.g. via a router/llama-swap config) — this endpoint
    only reports what's already there, it doesn't define models itself."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{host.rstrip('/')}/v1/models")
        response.raise_for_status()
        data = response.json().get("data") or []
    return [
        ChatModelInfo(
            id=model["id"],
            loaded=(model.get("status") or {}).get("value") == "loaded",
            vision="image"
            in (
                (model.get("architecture") or {}).get("input_modalities")
                or []
            ),
        )
        for model in data
    ]


async def _supports_vision(host: str) -> bool:
    """Query llama.cpp for whether the currently loaded model supports
    image input. Returns False if the probe fails, in which case images
    are conservatively left out of the request rather than risking a
    hard failure from a model that can't accept them."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{host.rstrip('/')}/props")
            response.raise_for_status()
            return bool(response.json().get("modalities", {}).get("vision"))
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to probe llama.cpp model modalities", exc_info=True)
        return False


async def stream_chat_response(
    host: str,
    model: str,
    question: str,
    note: Note,
    attachment_filenames: List[str],
    history: List[ChatMessage] = None,
) -> AsyncIterator[bytes]:
    """Yield newline-delimited JSON events for a chat response grounded in
    the given note and its attachments: 'token' events with streamed text,
    an 'edit' event if the model proposes a note change, then a 'done'
    event. Yields a single 'error' event instead if the llama.cpp server
    can't be reached."""
    note_content = note.content or ""
    if len(note_content) > MAX_NOTE_CONTENT_CHARS:
        note_content = note_content[:MAX_NOTE_CONTENT_CHARS] + "\n...(truncated)"

    images, attachments_text = _load_attachments(attachment_filenames)
    use_vision = bool(images) and await _supports_vision(host)

    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        title=note.title, content=note_content
    )
    if attachments_text:
        system_content += (
            "\n\nBelow are files attached to the note, for context only. "
            "They are NOT part of the note itself — never include any of "
            "this text if you propose an edit.\n\n" + attachments_text
        )
    if images and not use_vision:
        system_content += (
            "\n\n(This note has image attachments, but the current model "
            "can't read images.)"
        )
    system_content += (
        "\n\nWhenever the user wants the note changed — however they "
        "phrase it, including a casual 'yes' or 'go ahead' confirming "
        "something discussed earlier — call the edit_note tool "
        "instead of just describing the change in words. Never "
        "rewrite the note from scratch: edit_note only takes a small "
        "'find' snippet and its 'replace' text, so everything else in "
        "the note is preserved automatically. Place additions where "
        "they best fit the note's existing structure (e.g. next to a "
        "similar list item, under the most relevant heading) rather "
        "than always at the end, unless the user asked for it to be "
        "appended. See the tool's description for the exact rules."
    )

    if use_vision:
        content_parts = [{"type": "text", "text": question}]
        for mime_type, image_b64 in images:
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                }
            )
        user_message = {"role": "user", "content": content_parts}
    else:
        user_message = {"role": "user", "content": question}

    history_messages = [
        {"role": message.role, "content": message.content}
        for message in (history or [])[-MAX_HISTORY_MESSAGES:]
    ]

    # The context window is fixed by the llama.cpp server's own --ctx-size
    # startup flag rather than anything settable per-request, so there's no
    # equivalent of Ollama's `options.num_ctx` to pass here.
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            *history_messages,
            user_message,
        ],
        "stream": True,
        "tools": [EDIT_NOTE_TOOL],
    }

    # Edits are applied as find/replace snippets against the note's real,
    # untruncated content (not the possibly-truncated `note_content` shown
    # in the prompt) and accumulated across every edit_note call in this
    # response, so several proposed changes compose into one final diff.
    current_content = note.content or ""
    had_edit = False

    # OpenAI-style streaming sends tool calls as incremental fragments
    # (name in the first fragment, arguments dribbled out chunk by chunk)
    # keyed by index, rather than Ollama's whole-tool-call-per-chunk
    # format — so fragments are accumulated here and only acted on once
    # the stream ends.
    tool_calls_acc = {}

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream(
                "POST",
                f"{host.rstrip('/')}/v1/chat/completions",
                json=request_body,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error(
                        f"llama.cpp returned {response.status_code}: {body}"
                    )
                    raise LlamaCppUnavailableError()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    token_content = delta.get("content")
                    if token_content:
                        yield _event("token", content=token_content)
                    reasoning_content = delta.get("reasoning_content")
                    if reasoning_content:
                        yield _event("reasoning", content=reasoning_content)
                    for tool_call in delta.get("tool_calls") or []:
                        index = tool_call.get("index", 0)
                        entry = tool_calls_acc.setdefault(
                            index, {"name": "", "arguments": ""}
                        )
                        function = tool_call.get("function") or {}
                        if function.get("name"):
                            entry["name"] = function["name"]
                        if function.get("arguments"):
                            entry["arguments"] += function["arguments"]
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        if finish_reason == "length":
                            yield _event(
                                "notice",
                                message=(
                                    "The response was cut off because it "
                                    "reached the model's output limit."
                                ),
                            )
                        break
    except (httpx.HTTPError, LlamaCppUnavailableError):
        logger.warning("Failed to reach llama.cpp", exc_info=True)
        yield _event("error", message=api_messages.llamacpp_unreachable)
        return

    for index in sorted(tool_calls_acc):
        entry = tool_calls_acc[index]
        if entry["name"] != "edit_note":
            continue
        try:
            arguments = json.loads(entry["arguments"] or "{}")
        except ValueError:
            arguments = {}
        find = (arguments or {}).get("find")
        replace = (arguments or {}).get("replace")
        if not isinstance(find, str) or not isinstance(replace, str):
            continue
        find = _unescape_stray_newlines(find)
        replace = _unescape_stray_newlines(replace)
        new_content, error = _apply_edit(current_content, find, replace)
        if error:
            logger.warning(
                f"Model proposed an unapplicable edit ({error}): "
                f"find={find!r}"
            )
            yield _event(
                "edit_error",
                message=(
                    "The AI tried to change part of the note it "
                    "couldn't precisely locate, so that change was "
                    "skipped."
                ),
            )
            continue
        current_content = new_content
        had_edit = True

    if had_edit:
        yield _event(
            "edit",
            content=current_content,
            diff=_unified_diff(note.content, current_content),
        )

    yield _event("done")
