import json
from typing import AsyncIterator

import httpx

from helpers import CustomBaseModel
from logger import logger
from notes.models import Note

MAX_NOTE_CONTENT_CHARS = 6000

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant answering questions \
about the user's note titled "{title}". Only use the information in the \
note below to answer. If the note doesn't contain the answer, say so \
honestly rather than guessing.

Note:

{content}"""


class ChatRequest(CustomBaseModel):
    question: str
    note_title: str


class OllamaUnavailableError(Exception):
    pass


def _event(event_type: str, **fields) -> bytes:
    return (json.dumps({"type": event_type, **fields}) + "\n").encode()


async def stream_chat_response(
    host: str,
    model: str,
    question: str,
    note: Note,
) -> AsyncIterator[bytes]:
    """Yield newline-delimited JSON events for a chat response grounded in
    the given note: one or more 'token' events, then a 'done' event. Yields
    a single 'error' event instead if Ollama can't be reached."""
    note_content = note.content or ""
    if len(note_content) > MAX_NOTE_CONTENT_CHARS:
        note_content = note_content[:MAX_NOTE_CONTENT_CHARS] + "\n...(truncated)"

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT_TEMPLATE.format(
                title=note.title, content=note_content
            ),
        },
        {"role": "user", "content": question},
    ]

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{host.rstrip('/')}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
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
                    token_content = chunk.get("message", {}).get("content")
                    if token_content:
                        yield _event("token", content=token_content)
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
