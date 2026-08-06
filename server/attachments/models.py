from typing import List

from helpers import CustomBaseModel


class AttachmentCreateResponse(CustomBaseModel):
    filename: str
    url: str


class AttachmentInfo(CustomBaseModel):
    filename: str
    url: str
    size: int
    last_modified: float
    notes: List[str] = []
