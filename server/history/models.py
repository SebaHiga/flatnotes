from typing import Literal, Optional

from helpers import CustomBaseModel


class HistoryEntry(CustomBaseModel):
    commit_hash: str
    timestamp: float
    change_type: Literal["create", "update", "rename", "delete"]
    title: str
    old_title: Optional[str] = None


class HistoryVersion(CustomBaseModel):
    commit_hash: str
    title: str
    content: str
    timestamp: float


class HistoryDiff(CustomBaseModel):
    commit_hash: str
    parent_commit_hash: Optional[str] = None
    old_title: Optional[str] = None
    new_title: str
    diff: str
