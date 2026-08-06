import os
import threading
from typing import List, Optional

from git import Actor, Repo

from helpers import get_env, is_valid_filename
from logger import logger
from notes.models import Note

from ..base import BaseHistory
from ..models import HistoryDiff, HistoryEntry, HistoryVersion

MARKDOWN_EXT = ".md"
COMMIT_AUTHOR = Actor("flatnotes", "flatnotes@localhost")
# Git's well-known hash for the tree of an empty commit. Used as the "parent"
# when diffing a commit that has no real parent.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class FileSystemHistory(BaseHistory):
    def __init__(self):
        self.notes_path = get_env("FLATNOTES_PATH", mandatory=True)
        self.history_path = os.path.join(
            self.notes_path, ".flatnotes", "history"
        )
        self._lock = threading.Lock()
        self.repo = self._load_or_init_repo()

    def record_create(
        self, note: Note, restore_source: Optional[str] = None
    ) -> None:
        """Record the creation of a note."""
        with self._lock:
            self._write_mirror(note.title, note.content)
            self.repo.index.add([self._mirror_path(note.title)])
            message = (
                self._restore_message(note.title, restore_source)
                if restore_source
                else f"Create '{note.title}'"
            )
            self._commit(message)

    def record_update(
        self,
        note: Note,
        old_title: Optional[str] = None,
        restore_source: Optional[str] = None,
    ) -> None:
        """Record an update to a note, including a rename if old_title is
        given."""
        with self._lock:
            renamed = old_title is not None and old_title != note.title
            if renamed:
                self._move_mirror(old_title, note.title)
            self._write_mirror(note.title, note.content)
            self.repo.index.add([self._mirror_path(note.title)])
            if restore_source:
                message = self._restore_message(note.title, restore_source)
            elif renamed:
                message = f"Rename '{old_title}' to '{note.title}'"
            else:
                message = f"Update '{note.title}'"
            self._commit(message)

    def record_delete(self, title: str) -> None:
        """Record the deletion of a note."""
        with self._lock:
            if not os.path.isfile(self._mirror_path(title)):
                # Nothing was ever mirrored for this note (e.g. it was
                # created and deleted before history existed).
                return
            self.repo.index.remove(
                [self._mirror_path(title)], working_tree=True
            )
            self._commit(f"Delete '{title}'")

    def reconcile(self) -> None:
        """Detect and record any changes made to notes outside of the
        flatnotes API (e.g. direct filesystem edits) since the last
        reconciliation.

        Note: A rename performed outside the app is indistinguishable from a
        delete followed by a create, so it will be recorded as two separate
        commits rather than a single 'Rename' commit."""
        with self._lock:
            live = set(self._list_note_filenames(self.notes_path))
            mirrored = set(self._list_note_filenames(self.history_path))

            for filename in sorted(live - mirrored):
                self._reconcile_write(filename, "Create")
            for filename in sorted(live & mirrored):
                live_content = self._read(self.notes_path, filename)
                mirrored_content = self._read(self.history_path, filename)
                if live_content != mirrored_content:
                    self._reconcile_write(filename, "Update")
            for filename in sorted(mirrored - live):
                title = self._strip_ext(filename)
                self.repo.index.remove(
                    [self._mirror_path(title)], working_tree=True
                )
                self._commit(
                    f"Delete '{title}' (detected external change)"
                )

    def list_versions(self, title: str) -> List[HistoryEntry]:
        """Return the version history for a specific note, most recent
        first."""
        is_valid_filename(title)
        log_output = self.repo.git.log(
            "--follow", "--pretty=format:%H", "--", title + MARKDOWN_EXT
        )
        if not log_output:
            return []
        return [
            self._entry_from_commit(self.repo.commit(commit_hash))
            for commit_hash in log_output.splitlines()
        ]

    def get_version(self, title: str, commit_hash: str) -> HistoryVersion:
        """Return the content of a note as of a specific version."""
        is_valid_filename(title)
        entry = self._find_entry(title, commit_hash)
        if entry.change_type == "delete":
            raise FileNotFoundError(
                f"Version '{commit_hash}' of '{title}' has no content "
                "(it represents a deletion)."
            )
        commit = self.repo.commit(commit_hash)
        path = entry.title + MARKDOWN_EXT
        try:
            blob = commit.tree / path
        except KeyError:
            raise FileNotFoundError(
                f"'{path}' not found in commit '{commit_hash}'."
            )
        content = blob.data_stream.read().decode("utf-8")
        return HistoryVersion(
            commit_hash=commit.hexsha,
            title=entry.title,
            content=content,
            timestamp=commit.committed_date,
        )

    def get_diff(self, title: str, commit_hash: str) -> HistoryDiff:
        """Return the diff introduced by a specific version."""
        is_valid_filename(title)
        entry = self._find_entry(title, commit_hash)
        commit = self.repo.commit(commit_hash)
        parent = commit.parents[0] if commit.parents else None
        diff_text = self.repo.git.diff(
            parent.hexsha if parent else EMPTY_TREE_SHA,
            commit.hexsha,
            "-M",
        )
        return HistoryDiff(
            commit_hash=commit.hexsha,
            parent_commit_hash=parent.hexsha if parent else None,
            old_title=entry.old_title,
            new_title=entry.title,
            diff=diff_text,
        )

    def _load_or_init_repo(self) -> Repo:
        """Load the history mirror repo, initializing it (with a seed
        commit so HEAD always exists) if it doesn't already exist."""
        if os.path.isdir(os.path.join(self.history_path, ".git")):
            return Repo(self.history_path)
        os.makedirs(self.history_path, exist_ok=True)
        repo = Repo.init(self.history_path)
        repo.index.commit(
            "Initialize flatnotes history",
            author=COMMIT_AUTHOR,
            committer=COMMIT_AUTHOR,
            skip_hooks=True,
        )
        return repo

    def _commit(self, message: str) -> Optional[str]:
        """Commit whatever is currently staged. Returns the new commit hash,
        or None if nothing was staged (i.e. this would have been an empty
        commit)."""
        if not self.repo.git.diff("--cached", "--name-only").strip():
            return None
        commit = self.repo.index.commit(
            message,
            author=COMMIT_AUTHOR,
            committer=COMMIT_AUTHOR,
            skip_hooks=True,
        )
        return commit.hexsha

    def _reconcile_write(self, filename: str, verb: str) -> None:
        title = self._strip_ext(filename)
        content = self._read(self.notes_path, filename)
        self._write_mirror(title, content)
        self.repo.index.add([self._mirror_path(title)])
        self._commit(f"{verb} '{title}' (detected external change)")

    def _entry_from_commit(self, commit) -> HistoryEntry:
        parent = commit.parents[0] if commit.parents else None
        status_output = self.repo.git.diff(
            parent.hexsha if parent else EMPTY_TREE_SHA,
            commit.hexsha,
            "--name-status",
            "-M",
        )
        change_type = "update"
        old_title = None
        resolved_title = None
        for line in status_output.splitlines():
            parts = line.split("\t")
            code = parts[0]
            if code.startswith("A"):
                change_type = "create"
                resolved_title = self._strip_ext(parts[1])
            elif code.startswith("D"):
                change_type = "delete"
                resolved_title = self._strip_ext(parts[1])
            elif code.startswith("R"):
                change_type = "rename"
                old_title = self._strip_ext(parts[1])
                resolved_title = self._strip_ext(parts[2])
            elif code.startswith("M"):
                change_type = "update"
                resolved_title = self._strip_ext(parts[1])
        return HistoryEntry(
            commit_hash=commit.hexsha,
            timestamp=commit.committed_date,
            change_type=change_type,
            title=resolved_title,
            old_title=old_title,
        )

    def _find_entry(self, title: str, commit_hash: str) -> HistoryEntry:
        for entry in self.list_versions(title):
            if entry.commit_hash == commit_hash:
                return entry
        raise FileNotFoundError(
            f"No such version '{commit_hash}' for note '{title}'."
        )

    @staticmethod
    def _restore_message(title: str, restore_source: str) -> str:
        return f"Restore '{title}' to version {restore_source[:7]}"

    def _mirror_path(self, title: str) -> str:
        return os.path.join(self.history_path, title + MARKDOWN_EXT)

    def _write_mirror(self, title: str, content: str) -> None:
        with open(self._mirror_path(title), "w") as f:
            f.write(content or "")

    def _move_mirror(self, old_title: str, new_title: str) -> None:
        old_path = self._mirror_path(old_title)
        if not os.path.isfile(old_path):
            # Nothing to move from (e.g. the note predates history and
            # hasn't been reconciled yet); the subsequent write will create
            # the new mirror file as if it were new.
            return
        new_path = self._mirror_path(new_title)
        self.repo.index.move([old_path, new_path])

    @staticmethod
    def _read(directory: str, filename: str) -> str:
        with open(os.path.join(directory, filename), "r") as f:
            return f.read()

    @staticmethod
    def _list_note_filenames(directory: str) -> List[str]:
        return [
            filename
            for filename in os.listdir(directory)
            if filename.endswith(MARKDOWN_EXT)
            and os.path.isfile(os.path.join(directory, filename))
        ]

    @staticmethod
    def _strip_ext(filename: str) -> str:
        return os.path.splitext(filename)[0]
