from abc import ABC, abstractmethod
from typing import List

from fastapi import UploadFile
from fastapi.responses import FileResponse

from .models import AttachmentCreateResponse, AttachmentInfo


class BaseAttachments(ABC):
    @abstractmethod
    def create(self, file: UploadFile) -> AttachmentCreateResponse:
        """Create a new attachment."""
        pass

    @abstractmethod
    def get(self, filename: str) -> FileResponse:
        """Get a specific attachment."""
        pass

    @abstractmethod
    def list(self) -> List[AttachmentInfo]:
        """List all attachments."""
        pass

    @abstractmethod
    def delete(self, filename: str) -> None:
        """Delete a specific attachment."""
        pass
