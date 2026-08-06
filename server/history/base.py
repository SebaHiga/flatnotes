from abc import ABC, abstractmethod
from typing import List, Optional

from notes.models import Note

from .models import HistoryDiff, HistoryEntry, HistoryVersion


class BaseHistory(ABC):
    @abstractmethod
    def record_create(
        self, note: Note, restore_source: Optional[str] = None
    ) -> None:
        """Record the creation of a note."""
        pass

    @abstractmethod
    def record_update(
        self,
        note: Note,
        old_title: Optional[str] = None,
        restore_source: Optional[str] = None,
    ) -> None:
        """Record an update to a note, including a rename if old_title is
        given."""
        pass

    @abstractmethod
    def record_delete(self, title: str) -> None:
        """Record the deletion of a note."""
        pass

    @abstractmethod
    def reconcile(self) -> None:
        """Detect and record any changes made to notes outside of the
        flatnotes API (e.g. direct filesystem edits) since the last
        reconciliation."""
        pass

    @abstractmethod
    def list_versions(self, title: str) -> List[HistoryEntry]:
        """Return the version history for a specific note, most recent
        first."""
        pass

    @abstractmethod
    def get_version(self, title: str, commit_hash: str) -> HistoryVersion:
        """Return the content of a note as of a specific version."""
        pass

    @abstractmethod
    def get_diff(self, title: str, commit_hash: str) -> HistoryDiff:
        """Return the diff introduced by a specific version."""
        pass
