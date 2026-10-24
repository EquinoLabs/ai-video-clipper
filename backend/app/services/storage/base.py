"""Storage service abstract interface."""

from abc import ABC, abstractmethod
from typing import Optional


class StorageProvider(ABC):
    """Abstract interface for media storage (Cloudflare R2 or local mock)."""

    @abstractmethod
    async def generate_signed_upload_url(
        self,
        object_key: str,
        content_type: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a short-lived presigned URL for direct client upload."""
        pass

    @abstractmethod
    async def generate_signed_download_url(
        self,
        object_key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a short-lived presigned URL for client download."""
        pass

    @abstractmethod
    async def verify_object_exists(self, object_key: str) -> bool:
        """Check whether the given object key exists remotely."""
        pass

    @abstractmethod
    async def delete_object(self, object_key: str) -> bool:
        """Delete an object from storage."""
        pass
