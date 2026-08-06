import base64
import difflib
import json
import os
from typing import AsyncIterator, List

import httpx
import pypdf

from helpers import CustomBaseModel, get_env
from logger import logger
from notes.models import Note

MAX_NOTE_CONTENT_CHARS = 6000
MAX_ATTACHMENT_TEXT_CHARS = 4000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log", ".py", ".js",
    ".ts", ".html", ".css", ".xml", ".ini", ".toml", ".sh",
}

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant answering questions \
about the user's note titled "{title}".

The note's exact current content is reproduced below between the \
-----BEGIN NOTE----- and -----END NOTE----- markers, and nowhere else in \
this prompt. Only use the information between those markers (and any \
attached files described further below) to answer questions. If it \
doesn't contain the answer, say so honestly rather than guessing.

-----BEGIN NOTE-----
{content}
-----END NOTE-----"""

UPDATE_NOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_note",
        "description": (
            "Propose a full replacement for the note's content. Only call "
            "this when the user has explicitly asked you to change, fix, "
            "add to, or rewrite the note. The `content` argument must be a "
            "revised version of ONLY the text found between the "
            "-----BEGIN NOTE----- and -----END NOTE----- markers in the "
            "system prompt — never include attached-file text, these "
            "instructions, or the markers themselves."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The complete new content of the note, in "
                        "markdown, replacing everything between the "
                        "-----BEGIN NOTE----- / -----END NOTE----- markers."
                    ),
                }
            },
            "required": ["content"],
        },
    },
}


class ChatRequest(CustomBaseModel):
    question: str
    note_title: str


class OllamaUnavailableError(Exception):
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
    Images are returned as base64 strings (for vision-capable models);
    text files and PDFs (text extracted via pypdf) are concatenated into a
    single text block. Missing, oversized, or unsupported files are
    silently skipped."""
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
        if ext in IMAGE_EXTENSIONS:
            if len(images) >= MAX_IMAGES or size > MAX_IMAGE_BYTES:
                continue
            with open(path, "rb") as f:
                images.append(base64.b64encode(f.read()).decode())
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


def _unified_diff(old_content: str, new_content: str) -> str:
    diff_lines = difflib.unified_diff(
        (old_content or "").splitlines(),
        (new_content or "").splitlines(),
        lineterm="",
    )
    return "\n".join(diff_lines)


async def _model_capabilities(host: str, model: str) -> set:
    """Query Ollama for the capabilities (e.g. 'vision', 'tools') of the
    configured model. Returns an empty set if the probe fails, in which
    case vision/tool features are conservatively left disabled."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{host.rstrip('/')}/api/show", json={"model": model}
            )
            response.raise_for_status()
            return set(response.json().get("capabilities", []))
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to probe Ollama model capabilities", exc_info=True)
        return set()


async def stream_chat_response(
    host: str,
    model: str,
    question: str,
    note: Note,
    attachment_filenames: List[str],
) -> AsyncIterator[bytes]:
    """Yield newline-delimited JSON events for a chat response grounded in
    the given note and its attachments: 'token' events with streamed text,
    an 'edit' event if the model proposes a note change, then a 'done'
    event. Yields a single 'error' event instead if Ollama can't be
    reached."""
    note_content = note.content or ""
    if len(note_content) > MAX_NOTE_CONTENT_CHARS:
        note_content = note_content[:MAX_NOTE_CONTENT_CHARS] + "\n...(truncated)"

    images, attachments_text = _load_attachments(attachment_filenames)
    capabilities = await _model_capabilities(host, model)
    use_tools = "tools" in capabilities
    use_vision = "vision" in capabilities and bool(images)

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
    if use_tools:
        system_content += (
            "\n\nIf the user asks you to change, fix, extend, or rewrite "
            "the note, call the update_note tool with the complete new "
            "note content (see its description for exactly what to "
            "include) rather than just describing the change in words."
        )

    user_message = {"role": "user", "content": question}
    if use_vision:
        user_message["images"] = images

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            user_message,
        ],
        "stream": True,
    }
    if use_tools:
        request_body["tools"] = [UPDATE_NOTE_TOOL]

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream(
                "POST",
                f"{host.rstrip('/')}/api/chat",
                json=request_body,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error(
                        f"Ollama returned {response.status_code}: {body}"
                    )
                    raise OllamaUnavailableError()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    message = chunk.get("message", {})
                    token_content = message.get("content")
                    if token_content:
                        yield _event("token", content=token_content)
                    for tool_call in message.get("tool_calls") or []:
                        function = tool_call.get("function", {})
                        if function.get("name") != "update_note":
                            continue
                        arguments = function.get("arguments")
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except ValueError:
                                arguments = {}
                        new_content = (arguments or {}).get("content")
                        if isinstance(new_content, str):
                            yield _event(
                                "edit",
                                content=new_content,
                                diff=_unified_diff(note.content, new_content),
                            )
                    if chunk.get("done"):
                        break
    except (httpx.HTTPError, OllamaUnavailableError):
        logger.warning("Failed to reach Ollama", exc_info=True)
        yield _event(
            "error",
            message=(
                "Could not reach the Ollama server. Make sure it's "
                "running and reachable."
            ),
        )
        return

    yield _event("done")
