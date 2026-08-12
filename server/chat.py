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
# History messages aren't length-limited individually (unlike note content
# and attachments below), so this bounds their combined size too — without
# it, a long-running conversation could alone approach the context limit.
MAX_HISTORY_CHARS = 12000

MAX_NOTE_CONTENT_CHARS = 6000
MAX_ATTACHMENT_TEXT_CHARS = 4000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4

# Used to size the note content + attachment text budget off the model's
# actual n_ctx (see _content_char_budget) instead of the flat
# MAX_NOTE_CONTENT_CHARS / MAX_ATTACHMENT_TEXT_CHARS caps above, which stay
# only as the fallback when n_ctx can't be read.
CHARS_PER_TOKEN_ESTIMATE = 3.0
# Covers the system prompt scaffolding and the edit_note/read_attachment
# tool schemas, measured at ~1400 tokens with some buffer — everything in
# the request that isn't note content, history, attachments, or the
# response.
SCAFFOLD_RESERVED_TOKENS = 1500
# Rough reserve for the response itself: normal answer text, or an
# edit_note/read_attachment tool call's arguments.
RESPONSE_RESERVED_TOKENS = 2000

# Token budgets for the graded reasoning-effort levels, applied via
# llama.cpp's reasoning_budget_tokens sampler-level cutoff (works for any
# model whose chat format has thinking tags, regardless of whether its
# template exposes a graded reasoning_effort variable itself). "max" has no
# real cap (unbounded thinking_budget_tokens) so its entry here is only a
# practical reserve for _content_char_budget, not an enforced limit —
# a model that reasons far past it can still exceed the context window;
# llama.cpp's own context handling is the final backstop at that point.
REASONING_EFFORT_TOKEN_BUDGETS = {"low": 512, "medium": 2048, "high": 8192}
REASONING_EFFORT_RESERVE_TOKENS = {
    "off": 0,
    "low": 512,
    "medium": 2048,
    "high": 8192,
    "max": 16384,
}

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

READ_ATTACHMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "read_attachment",
        "description": (
            "Read the contents of one of this note's attachments — a "
            "text file, PDF, or image — by its exact filename. "
            "Attachments referenced by the note are NOT loaded "
            "automatically (only ones the user attached to this specific "
            "question are); only call this for one actually listed as "
            "available in the system prompt, and only when its contents "
            "are actually needed to answer the question — don't call it "
            "speculatively or for every attachment a note happens to have."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "The exact attachment filename to read, exactly "
                        "as listed in the system prompt (e.g. "
                        "'photo3.png' or 'report.pdf')."
                    ),
                },
            },
            "required": ["filename"],
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
    # None leaves the model/server's own default thinking behaviour alone.
    reasoning_effort: Optional[
        Literal["off", "low", "medium", "high", "max"]
    ] = None
    # Filenames of attachments (typically images) uploaded for this
    # question specifically. Shown eagerly, unlike attachments merely
    # referenced somewhere in the note — attaching one to a question IS
    # the signal it's relevant, whereas the note's own attachments are
    # only fetched on demand (see stream_chat_response's read_attachment
    # tool) so they don't all get force-fed into every question asked.
    chat_attachment_filenames: List[str] = []


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


def _load_attachments(filenames: List[str], max_text_chars: int):
    """Eagerly loads the given attachment filenames — used for
    chat_attachment_filenames, the ones a user explicitly attached to a
    specific question (note-wide attachments are instead only fetched on
    demand via the read_attachment tool; see stream_chat_response).
    Returns (images, text_block, unshown_images, shown_image_filenames).
    Images are returned as (mime_type, base64_str) tuples, ready to embed
    as data URIs for vision-capable models; text files and PDFs (text
    extracted via pypdf) are concatenated into a single text block.
    max_text_chars is a SHARED budget across every text/PDF attachment
    combined, not a per-file cap — spent in filename order, and once
    exhausted, further text/PDF attachments are skipped entirely rather
    than each separately getting up to the full budget. unshown_images
    lists image filenames left out solely due to the MAX_IMAGES/
    MAX_IMAGE_BYTES caps (silently dropped — a handful of explicitly
    attached images blowing past a small cap isn't worth a round-trip to
    explain); shown_image_filenames is the filename for each entry in
    images, in the same order. Missing or unsupported files are silently
    skipped."""
    images = []
    shown_image_filenames = []
    unshown_images = []
    text_parts = []
    remaining_chars = max_text_chars
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
                unshown_images.append(filename)
                continue
            with open(path, "rb") as f:
                images.append((IMAGE_MIME_TYPES[ext], base64.b64encode(f.read()).decode()))
            shown_image_filenames.append(filename)
        elif ext in TEXT_ATTACHMENT_EXTENSIONS:
            if remaining_chars <= 0:
                continue
            with open(path, "r", errors="replace") as f:
                content = f.read(remaining_chars + 1)
            if len(content) > remaining_chars:
                content = content[:remaining_chars] + "\n...(truncated)"
            remaining_chars -= len(content)
            text_parts.append(f"### Attachment: {filename}\n{content}")
        elif ext == ".pdf":
            if remaining_chars <= 0:
                continue
            content = _extract_pdf_text(path).strip()
            if not content:
                continue
            if len(content) > remaining_chars:
                content = content[:remaining_chars] + "\n...(truncated)"
            remaining_chars -= len(content)
            text_parts.append(f"### Attachment: {filename}\n{content}")
    return images, "\n\n".join(text_parts), unshown_images, shown_image_filenames


def _classify_attachment(filename: str) -> Optional[str]:
    """Returns 'image', 'text', or 'pdf' by extension, or None for a type
    read_attachment can't handle."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_MIME_TYPES:
        return "image"
    if ext in TEXT_ATTACHMENT_EXTENSIONS:
        return "text"
    if ext == ".pdf":
        return "pdf"
    return None


def _read_attachment(filename: str, kind: str, remaining_text_chars: int):
    """Reads one attachment on demand for the read_attachment tool.
    Returns ('image', mime_type, base64_str) for images, ('text',
    content) for text/PDF (content capped at remaining_text_chars, the
    text/PDF budget still remaining this turn — see stream_chat_response),
    or None if it can't be read. Callers must have already validated
    filename against the note's own known fetchable attachments (see
    stream_chat_response) — this only additionally guards against path
    traversal, it doesn't scope access by note on its own."""
    if os.path.basename(filename) != filename:
        return None
    path = os.path.join(_attachments_dir(), filename)
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if kind == "image":
        if size > MAX_IMAGE_BYTES:
            return None
        ext = os.path.splitext(filename)[1].lower()
        with open(path, "rb") as f:
            return "image", IMAGE_MIME_TYPES[ext], base64.b64encode(f.read()).decode()
    if remaining_text_chars <= 0:
        return None
    if kind == "text":
        with open(path, "r", errors="replace") as f:
            content = f.read(remaining_text_chars + 1)
    elif kind == "pdf":
        content = _extract_pdf_text(path).strip()
        if not content:
            return None
    else:
        return None
    if len(content) > remaining_text_chars:
        content = content[:remaining_text_chars] + "\n...(truncated)"
    return "text", content


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


async def _get_model_n_ctx(host: str, model: str) -> Optional[int]:
    """Look up the selected model's context size via llama.cpp's
    /v1/models (its "meta" field reports n_ctx per model), so the
    attachment text budget can scale with what the model can actually
    hold rather than a fixed guess. Returns None if the probe fails or
    the model isn't listed with a usable n_ctx."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{host.rstrip('/')}/v1/models")
            response.raise_for_status()
            data = response.json().get("data") or []
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to probe llama.cpp model context size", exc_info=True)
        return None
    for entry in data:
        if entry.get("id") == model:
            n_ctx = (entry.get("meta") or {}).get("n_ctx")
            return n_ctx if isinstance(n_ctx, int) and n_ctx > 0 else None
    return None


async def _content_char_budget(
    host: str, model: str, reasoning_effort: Optional[str]
) -> int:
    """Size the combined note-content + attachment-text budget off the
    model's real n_ctx instead of the flat MAX_NOTE_CONTENT_CHARS /
    MAX_ATTACHMENT_TEXT_CHARS guesses, so large-context models don't still
    get long notes and PDFs cut off after a page or two. Reserves headroom
    for the system prompt scaffolding, history, and the response itself —
    including reasoning tokens, sized off reasoning_effort since a
    thinking response can itself use as many tokens as the rest of the
    prompt combined. Falls back to (and never drops below)
    MAX_NOTE_CONTENT_CHARS + MAX_ATTACHMENT_TEXT_CHARS if n_ctx can't be
    determined. Split between note content and attachments happens in the
    caller, since only it knows the note's actual length."""
    n_ctx = await _get_model_n_ctx(host, model)
    if not n_ctx:
        return MAX_NOTE_CONTENT_CHARS + MAX_ATTACHMENT_TEXT_CHARS
    # reasoning_effort of None means the model/template's own default
    # applies, which may or may not think — "medium" is assumed as a
    # reasonable middle-ground reserve for that unknown case.
    reasoning_reserve = REASONING_EFFORT_RESERVE_TOKENS.get(
        reasoning_effort, REASONING_EFFORT_RESERVE_TOKENS["medium"]
    )
    reserved_tokens = (
        SCAFFOLD_RESERVED_TOKENS
        + RESPONSE_RESERVED_TOKENS
        + reasoning_reserve
        + (MAX_HISTORY_CHARS / CHARS_PER_TOKEN_ESTIMATE)
    )
    budget_chars = int((n_ctx - reserved_tokens) * CHARS_PER_TOKEN_ESTIMATE)
    return max(MAX_NOTE_CONTENT_CHARS + MAX_ATTACHMENT_TEXT_CHARS, budget_chars)


# Bounds how many extra request/response round-trips a single answer can
# make to fetch attachments via read_attachment, so a model that keeps
# asking for attachments (or asks for one that's not found) can't loop
# indefinitely.
MAX_ATTACHMENT_FETCH_ROUNDS = 4


async def stream_chat_response(
    host: str,
    model: str,
    question: str,
    note: Note,
    note_attachment_filenames: List[str],
    chat_attachment_filenames: List[str],
    history: List[ChatMessage] = None,
    reasoning_effort: Optional[str] = None,
) -> AsyncIterator[bytes]:
    """Yield newline-delimited JSON events for a chat response grounded in
    the given note: 'token' events with streamed text, an 'edit' event if
    the model proposes a note change, then a 'done' event. Yields a single
    'error' event instead if the llama.cpp server can't be reached.

    note_attachment_filenames (attachments merely referenced somewhere in
    the note) are NOT loaded up front — only their filenames are listed,
    and the model fetches one via the read_attachment tool if it actually
    needs it, rather than every question paying for every attachment
    whether relevant or not. chat_attachment_filenames (attached to this
    specific question) ARE shown eagerly, since attaching one to a
    question is itself a signal it's relevant. May make several
    request/response round-trips to llama.cpp under the hood (see
    MAX_ATTACHMENT_FETCH_ROUNDS) if the model uses read_attachment, but
    this is invisible to the caller — still one token stream."""
    # Note content and attachment text share one n_ctx-sized pool rather
    # than each getting an independent flat cap — the note itself gets
    # priority (it's what the user is actually chatting about) up to
    # whatever's left after reserving a floor for on-demand attachment
    # fetches, so a long note only crowds out attachments, never the
    # reverse, and neither is capped tighter than the old flat limits on
    # a small-context model.
    content_char_budget = await _content_char_budget(host, model, reasoning_effort)
    note_content = note.content or ""
    note_content_budget = max(
        MAX_NOTE_CONTENT_CHARS, content_char_budget - MAX_ATTACHMENT_TEXT_CHARS
    )
    if len(note_content) > note_content_budget:
        note_content = note_content[:note_content_budget] + "\n...(truncated)"

    attachment_char_budget = max(
        MAX_ATTACHMENT_TEXT_CHARS, content_char_budget - len(note_content)
    )
    chat_images, chat_attachments_text, _, chat_shown_image_filenames = (
        _load_attachments(chat_attachment_filenames, attachment_char_budget)
    )

    # Classify the note's own attachments (existence + type only, nothing
    # read yet) into what read_attachment could fetch on demand, skipping
    # ones already shown eagerly above via chat_attachment_filenames.
    fetchable_by_kind = {"image": [], "text": [], "pdf": []}
    for filename in note_attachment_filenames:
        if filename in chat_attachment_filenames:
            continue
        kind = _classify_attachment(filename)
        if kind is None:
            continue
        try:
            os.path.getsize(os.path.join(_attachments_dir(), filename))
        except OSError:
            continue
        fetchable_by_kind[kind].append(filename)

    use_vision = bool(chat_images or fetchable_by_kind["image"]) and (
        await _supports_vision(host)
    )

    fetchable_kind_by_filename = {}
    for filename in fetchable_by_kind["text"] + fetchable_by_kind["pdf"]:
        fetchable_kind_by_filename[filename] = _classify_attachment(filename)
    if use_vision:
        for filename in fetchable_by_kind["image"]:
            fetchable_kind_by_filename[filename] = "image"

    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        title=note.title, content=note_content
    )
    if chat_attachments_text:
        system_content += (
            "\n\nThe user attached these files to this specific question "
            "(not part of the note itself — never include any of this "
            "text if you propose an edit):\n\n" + chat_attachments_text
        )
    if chat_images and not use_vision:
        system_content += (
            "\n\n(Image(s) were attached to this question, but the "
            "current model can't read images.)"
        )
    if fetchable_kind_by_filename:
        kind_labels = {"text": "text file", "pdf": "PDF", "image": "image"}
        listing = ", ".join(
            f"{filename} ({kind_labels[kind]})"
            for filename, kind in fetchable_kind_by_filename.items()
        )
        system_content += (
            "\n\nThis note also has these attachments. They are NOT "
            "loaded automatically — call the read_attachment tool with "
            "one's exact filename if its contents would actually help "
            "answer the question, rather than assuming it's relevant: "
            + listing
        )
    if fetchable_by_kind["image"] and not use_vision:
        system_content += (
            "\n\n(This note also has image attachments, but the current "
            "model can't read images.)"
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

    if chat_images and use_vision:
        content_parts = [{"type": "text", "text": question}]
        for mime_type, image_b64 in chat_images:
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                }
            )
        user_message = {"role": "user", "content": content_parts}
    else:
        user_message = {"role": "user", "content": question}

    # Trimmed from the oldest first, both by count (MAX_HISTORY_MESSAGES)
    # and combined size (MAX_HISTORY_CHARS) — messages aren't individually
    # length-limited, so a handful of long ones could otherwise use as much
    # context as everything else combined. Always keeps at least the single
    # most recent message even if it alone exceeds the char budget.
    history_messages = []
    history_chars_used = 0
    for message in reversed((history or [])[-MAX_HISTORY_MESSAGES:]):
        content = message.content or ""
        if history_messages and history_chars_used + len(content) > MAX_HISTORY_CHARS:
            break
        history_messages.append({"role": message.role, "content": content})
        history_chars_used += len(content)
    history_messages.reverse()

    tools = [EDIT_NOTE_TOOL]
    if fetchable_kind_by_filename:
        tools.append(READ_ATTACHMENT_TOOL)

    # Grows across rounds if the model calls read_attachment: an assistant
    # tool-call message plus its tool-result message(s) get appended, then
    # the loop below sends the whole thing back for a continuation. Kept
    # separate from `history` (the prior turns' {role, content} pairs the
    # client sent), since only this turn's tool-calling exchange needs the
    # full OpenAI tool_calls/tool-role structure.
    messages = [
        {"role": "system", "content": system_content},
        *history_messages,
        user_message,
    ]

    # enable_thinking is a template kwarg (only templates that check for it
    # honour it), while thinking_budget_tokens is enforced by llama.cpp's
    # sampler once the model starts emitting its format's thinking tags —
    # the two are independent, so both are set together here to actually
    # turn thinking on/off *and* cap it, rather than relying on either one
    # alone. "max" still forces thinking on but leaves it uncapped; only
    # the unset default leaves the model's own default behaviour untouched.
    reasoning_fields = {}
    if reasoning_effort is not None:
        reasoning_fields["chat_template_kwargs"] = {
            "enable_thinking": reasoning_effort != "off"
        }
        if reasoning_effort in REASONING_EFFORT_TOKEN_BUDGETS:
            reasoning_fields["thinking_budget_tokens"] = (
                REASONING_EFFORT_TOKEN_BUDGETS[reasoning_effort]
            )

    # Edits are applied as find/replace snippets against the note's real,
    # untruncated content (not the possibly-truncated `note_content` shown
    # in the prompt) and accumulated across every edit_note call across
    # every round, so several proposed changes compose into one final diff.
    current_content = note.content or ""
    had_edit = False
    # Filenames already visible to the model — either shown eagerly above
    # or fetched via read_attachment in an earlier round — so a repeat
    # request for the same one is answered without re-sending it.
    shown_attachment_filenames = set(chat_shown_image_filenames)
    # The text/PDF budget still unspent this turn, shared across every
    # read_attachment call the same way _load_attachments shares it across
    # eagerly-loaded attachments (see _content_char_budget) — letting
    # each on-demand read separately claim the full budget could multiply
    # the total well past the model's actual context window.
    remaining_text_chars = attachment_char_budget - len(chat_attachments_text)
    # Counts rounds that fetched (or tried to fetch) a read_attachment
    # request, not every round overall — a round that only calls edit_note
    # doesn't consume this, and never triggers another round-trip either way.
    fetch_rounds_used = 0

    while True:
        # The context window is fixed by the llama.cpp server's own
        # --ctx-size startup flag rather than anything settable
        # per-request, so there's no equivalent of Ollama's `options.
        # num_ctx` to pass here.
        request_body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "tools": tools,
            **reasoning_fields,
        }

        # OpenAI-style streaming sends tool calls as incremental fragments
        # (id and name in the first fragment, arguments dribbled out chunk
        # by chunk) keyed by index, rather than Ollama's
        # whole-tool-call-per-chunk format — so fragments are accumulated
        # here and only acted on once the stream ends.
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
                                index, {"id": None, "name": "", "arguments": ""}
                            )
                            if tool_call.get("id"):
                                entry["id"] = tool_call["id"]
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
                                        "The response was cut off because "
                                        "it reached the model's output "
                                        "limit."
                                    ),
                                )
                            break
        except (httpx.HTTPError, LlamaCppUnavailableError):
            logger.warning("Failed to reach llama.cpp", exc_info=True)
            yield _event("error", message=api_messages.llamacpp_unreachable)
            return

        if not tool_calls_acc:
            break  # Plain answer — nothing more to do.

        # A real API response always ids its tool calls (confirmed against
        # llama.cpp directly), but fall back to a stable synthetic one
        # rather than trip over a None id if that's ever not true.
        for index in sorted(tool_calls_acc):
            entry = tool_calls_acc[index]
            if not entry["id"]:
                entry["id"] = f"call_{index}"

        edit_calls = []
        read_calls = []
        for index in sorted(tool_calls_acc):
            entry = tool_calls_acc[index]
            if entry["name"] == "edit_note":
                edit_calls.append(entry)
            elif entry["name"] == "read_attachment":
                read_calls.append(entry)

        for entry in edit_calls:
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

        if not read_calls:
            break  # Only edits (if any) were requested — done, no continuation.

        # Tool-role content must be plain text, so a requested image
        # itself has to ride in a separate message right after its
        # tool-result acknowledgement (text/PDF reads instead go straight
        # into the tool-result message, since that's already plain text).
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": entry["id"],
                        "type": "function",
                        "function": {
                            "name": entry["name"],
                            "arguments": entry["arguments"],
                        },
                    }
                    for entry in edit_calls + read_calls
                ],
            }
        )
        for entry in edit_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": entry["id"],
                    "content": "Edit proposed to the user (shown separately as a diff).",
                }
            )

        # Once the round budget is spent, attachments stop being fetched
        # (and the tool is dropped below so it can't be called again next
        # round) — but the model still gets a tool-result message either
        # way, so it always has a chance to respond in text instead of the
        # turn just silently going quiet.
        rounds_remain = fetch_rounds_used < MAX_ATTACHMENT_FETCH_ROUNDS
        for entry in read_calls:
            try:
                arguments = json.loads(entry["arguments"] or "{}")
            except ValueError:
                arguments = {}
            filename = (arguments or {}).get("filename")
            result = None
            if isinstance(filename, str) and filename in shown_attachment_filenames:
                tool_message = f"'{filename}' was already shown above."
            elif (
                not isinstance(filename, str)
                or filename not in fetchable_kind_by_filename
            ):
                tool_message = f"No attachment named '{filename}' was found."
            elif not rounds_remain:
                tool_message = (
                    "Too many attachments requested this turn — answer "
                    "with what's already available instead."
                )
            else:
                kind = fetchable_kind_by_filename[filename]
                result = _read_attachment(filename, kind, remaining_text_chars)
                if result and result[0] == "text":
                    tool_message = f"### Attachment: {filename}\n{result[1]}"
                    remaining_text_chars -= len(result[1])
                    shown_attachment_filenames.add(filename)
                elif result:
                    tool_message = f"Showing '{filename}' below."
                    shown_attachment_filenames.add(filename)
                else:
                    tool_message = f"Couldn't read '{filename}'."
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": entry["id"],
                    "content": tool_message,
                }
            )
            if result and result[0] == "image":
                _, mime_type, image_b64 = result
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_b64}"
                                },
                            }
                        ],
                    }
                )

        fetch_rounds_used += 1
        if not rounds_remain:
            tools = [EDIT_NOTE_TOOL]

    if had_edit:
        yield _event(
            "edit",
            content=current_content,
            diff=_unified_diff(note.content, current_content),
        )

    yield _event("done")
