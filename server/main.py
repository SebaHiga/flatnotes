from typing import List, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import api_messages
import chat
from attachments.base import BaseAttachments
from attachments.models import AttachmentCreateResponse, AttachmentInfo
from auth.base import BaseAuth
from auth.models import Login, Token
from global_config import AuthType, GlobalConfig, GlobalConfigResponseModel
from helpers import replace_base_href
from history.base import BaseHistory
from history.models import HistoryDiff, HistoryEntry, HistoryVersion
from logger import logger
from notes.base import BaseNotes
from notes.models import Note, NoteCreate, NoteUpdate, SearchResult

global_config = GlobalConfig()
auth: BaseAuth = global_config.load_auth()
note_storage: BaseNotes = global_config.load_note_storage()
attachment_storage: BaseAttachments = global_config.load_attachment_storage()
history_storage: BaseHistory = global_config.load_history_storage()
try:
    history_storage.reconcile()
except Exception:
    logger.warning(
        "Failed to reconcile note history on startup", exc_info=True
    )
auth_deps = [Depends(auth.authenticate)] if auth else []
router = APIRouter()
app = FastAPI(
    docs_url=global_config.path_prefix + "/docs",
    openapi_url=global_config.path_prefix + "/openapi.json",
)
replace_base_href("client/dist/index.html", global_config.path_prefix)


# region UI
@router.get("/", include_in_schema=False)
@router.get("/login", include_in_schema=False)
@router.get("/search", include_in_schema=False)
@router.get("/new", include_in_schema=False)
@router.get("/note/{title}", include_in_schema=False)
@router.get("/note/{title}/history", include_in_schema=False)
@router.get("/attachments", include_in_schema=False)
def root(title: str = ""):
    with open("client/dist/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)


# endregion


# region Auth
if global_config.auth_type not in [AuthType.NONE, AuthType.READ_ONLY]:

    @router.post("/api/token", response_model=Token)
    def token(data: Login):
        try:
            return auth.login(data)
        except ValueError:
            raise HTTPException(
                status_code=401, detail=api_messages.login_failed
            )


@router.get("/api/auth-check", dependencies=auth_deps)
def auth_check() -> str:
    """A lightweight endpoint that simply returns 'OK' if the user is
    authenticated."""
    return "OK"


# endregion


# region Notes
# Get Note
@router.get(
    "/api/notes/{title}",
    dependencies=auth_deps,
    response_model=Note,
)
def get_note(title: str):
    """Get a specific note."""
    try:
        return note_storage.get(title)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=api_messages.invalid_note_title
        )
    except FileNotFoundError:
        raise HTTPException(404, api_messages.note_not_found)


# Get Note History
@router.get(
    "/api/notes/{title}/history",
    dependencies=auth_deps,
    response_model=List[HistoryEntry],
)
def get_note_history(title: str):
    """Get the version history for a specific note, most recent first."""
    try:
        history_storage.reconcile()
    except Exception:
        logger.warning("Failed to reconcile note history", exc_info=True)
    try:
        return history_storage.list_versions(title)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=api_messages.invalid_note_title
        )


# Get Note History Version
@router.get(
    "/api/notes/{title}/history/{commit_hash}",
    dependencies=auth_deps,
    response_model=HistoryVersion,
)
def get_note_history_version(title: str, commit_hash: str):
    """Get the content of a note as of a specific version."""
    try:
        return history_storage.get_version(title, commit_hash)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=api_messages.invalid_note_title
        )
    except FileNotFoundError:
        raise HTTPException(404, api_messages.history_not_found)


# Get Note History Diff
@router.get(
    "/api/notes/{title}/history/{commit_hash}/diff",
    dependencies=auth_deps,
    response_model=HistoryDiff,
)
def get_note_history_diff(title: str, commit_hash: str):
    """Get the diff introduced by a specific version of a note."""
    try:
        return history_storage.get_diff(title, commit_hash)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=api_messages.invalid_note_title
        )
    except FileNotFoundError:
        raise HTTPException(404, api_messages.history_not_found)


if global_config.auth_type != AuthType.READ_ONLY:

    # Create Note
    @router.post(
        "/api/notes",
        dependencies=auth_deps,
        response_model=Note,
    )
    def post_note(note: NoteCreate):
        """Create a new note."""
        try:
            created = note_storage.create(note)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=api_messages.invalid_note_title,
            )
        except FileExistsError:
            raise HTTPException(
                status_code=409, detail=api_messages.note_exists
            )
        try:
            history_storage.record_create(created)
        except Exception:
            logger.warning(
                f"Failed to record history for '{created.title}'",
                exc_info=True,
            )
        return created

    # Update Note
    @router.patch(
        "/api/notes/{title}",
        dependencies=auth_deps,
        response_model=Note,
    )
    def patch_note(title: str, data: NoteUpdate):
        try:
            updated = note_storage.update(title, data)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=api_messages.invalid_note_title,
            )
        except FileExistsError:
            raise HTTPException(
                status_code=409, detail=api_messages.note_exists
            )
        except FileNotFoundError:
            raise HTTPException(404, api_messages.note_not_found)
        try:
            history_storage.record_update(
                updated,
                old_title=title if updated.title != title else None,
            )
        except Exception:
            logger.warning(
                f"Failed to record history for '{updated.title}'",
                exc_info=True,
            )
        return updated

    # Restore Note History Version
    @router.post(
        "/api/notes/{title}/history/{commit_hash}/restore",
        dependencies=auth_deps,
        response_model=Note,
    )
    def restore_note_history_version(title: str, commit_hash: str):
        """Restore a note to a previous version. This creates a new
        version rather than rewriting history."""
        try:
            version = history_storage.get_version(title, commit_hash)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=api_messages.invalid_note_title
            )
        except FileNotFoundError:
            raise HTTPException(404, api_messages.history_not_found)

        try:
            restored = note_storage.update(
                title, NoteUpdate(new_content=version.content)
            )
            undeleted = False
        except FileNotFoundError:
            # The note is currently deleted; restoring "undeletes" it.
            restored = note_storage.create(
                NoteCreate(title=title, content=version.content)
            )
            undeleted = True

        try:
            if undeleted:
                history_storage.record_create(
                    restored, restore_source=commit_hash
                )
            else:
                history_storage.record_update(
                    restored, restore_source=commit_hash
                )
        except Exception:
            logger.warning(
                f"Failed to record history for '{title}'", exc_info=True
            )
        return restored

    # Delete Note
    @router.delete(
        "/api/notes/{title}",
        dependencies=auth_deps,
        response_model=None,
    )
    def delete_note(title: str):
        try:
            note_storage.delete(title)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=api_messages.invalid_note_title,
            )
        except FileNotFoundError:
            raise HTTPException(404, api_messages.note_not_found)
        try:
            history_storage.record_delete(title)
        except Exception:
            logger.warning(
                f"Failed to record history for '{title}'", exc_info=True
            )


# endregion


# region Search
@router.get(
    "/api/search",
    dependencies=auth_deps,
    response_model=List[SearchResult],
)
def search(
    term: str,
    sort: Literal["score", "title", "lastModified"] = "score",
    order: Literal["asc", "desc"] = "desc",
    limit: int = None,
):
    """Perform a full text search on all notes."""
    if sort == "lastModified":
        sort = "last_modified"
    return note_storage.search(term, sort=sort, order=order, limit=limit)


@router.get(
    "/api/tags",
    dependencies=auth_deps,
    response_model=List[str],
)
def get_tags():
    """Get a list of all indexed tags."""
    return note_storage.get_tags()


# endregion


# region Chat
@router.post("/api/chat", dependencies=auth_deps)
def post_chat(data: chat.ChatRequest):
    """Ask a question about a specific note, answered by a local Ollama
    model using only that note's content."""
    if not global_config.ollama_enabled:
        raise HTTPException(503, api_messages.chat_not_configured)
    try:
        note = note_storage.get(data.note_title)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=api_messages.invalid_note_title
        )
    except FileNotFoundError:
        raise HTTPException(404, api_messages.note_not_found)
    references = note_storage.get_attachment_references()
    attachment_filenames = [
        filename
        for filename, titles in references.items()
        if note.title in titles
    ]
    return StreamingResponse(
        chat.stream_chat_response(
            global_config.ollama_host,
            global_config.ollama_model,
            data.question,
            note,
            attachment_filenames,
        ),
        media_type="application/x-ndjson",
    )


# endregion


# region Config
@router.get("/api/config", response_model=GlobalConfigResponseModel)
def get_config():
    """Retrieve server-side config required for the UI."""
    return GlobalConfigResponseModel(
        auth_type=global_config.auth_type,
        quick_access_hide=global_config.quick_access_hide,
        quick_access_title=global_config.quick_access_title,
        quick_access_term=global_config.quick_access_term,
        quick_access_sort=global_config.quick_access_sort,
        quick_access_limit=global_config.quick_access_limit,
        ollama_enabled=global_config.ollama_enabled,
    )


# endregion


# region Attachments
# List Attachments
@router.get(
    "/api/attachments",
    dependencies=auth_deps,
    response_model=List[AttachmentInfo],
)
def get_attachments():
    """List all attachments along with the notes that reference them."""
    references = note_storage.get_attachment_references()
    attachments = attachment_storage.list()
    for attachment in attachments:
        attachment.notes = references.get(attachment.filename, [])
    return attachments


# Get Attachment
@router.get(
    "/api/attachments/{filename}",
    dependencies=auth_deps,
)
# Include a secondary route used to create relative URLs that can be used
# outside the context of flatnotes (e.g. "/attachments/image.jpg").
@router.get(
    "/attachments/{filename}",
    dependencies=auth_deps,
    include_in_schema=False,
)
def get_attachment(filename: str):
    """Download an attachment."""
    try:
        return attachment_storage.get(filename)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=api_messages.invalid_attachment_filename,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=api_messages.attachment_not_found
        )


if global_config.auth_type != AuthType.READ_ONLY:

    # Create Attachment
    @router.post(
        "/api/attachments",
        dependencies=auth_deps,
        response_model=AttachmentCreateResponse,
    )
    def post_attachment(file: UploadFile):
        """Upload an attachment."""
        try:
            return attachment_storage.create(file)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=api_messages.invalid_attachment_filename,
            )
        except FileExistsError:
            raise HTTPException(409, api_messages.attachment_exists)

    # Delete Attachment
    @router.delete(
        "/api/attachments/{filename}",
        dependencies=auth_deps,
        response_model=None,
    )
    def delete_attachment(filename: str):
        """Delete an attachment. Refuses to delete attachments that are
        still linked to from a note."""
        try:
            references = note_storage.get_attachment_references()
            if references.get(filename):
                raise HTTPException(409, api_messages.attachment_in_use)
            attachment_storage.delete(filename)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=api_messages.invalid_attachment_filename,
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=api_messages.attachment_not_found
            )


# endregion


# region Healthcheck
@router.get("/health")
def healthcheck() -> str:
    """A lightweight endpoint that simply returns 'OK' to indicate the server
    is running."""
    return "OK"


# endregion

app.include_router(router, prefix=global_config.path_prefix)
app.mount(
    global_config.path_prefix,
    StaticFiles(directory="client/dist"),
    name="dist",
)
