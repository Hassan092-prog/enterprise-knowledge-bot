"""
storage.py — Decoupled Distributed Object Storage Abstraction Layer (Pillar 4).
Supports LocalStorageProvider (default dev) and S3StorageProvider (MinIO / AWS S3).
"""
import io
import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional, Union, List

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from src.config import (
    STORAGE_BACKEND,
    S3_ENDPOINT_URL,
    S3_PUBLIC_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_BUCKET_NAME,
    S3_REGION,
    UPLOAD_DIR,
)

logger = logging.getLogger("src.storage")


def get_object_key(
    tenant_id: Optional[int] = None,
    filename: Optional[str] = None,
    is_global: bool = False,
    user_id: Optional[int] = None,
    **kwargs
) -> str:
    """
    Generate canonical multi-tenant namespaced object key:
    - Global:   tenants/{tenant_id}/global/{filename}
    - Personal: tenants/{tenant_id}/personal/{user_id}/{filename}
    """
    if "filename" in kwargs and filename is None:
        filename = kwargs["filename"]
    if "user_id" in kwargs and user_id is None:
        user_id = kwargs["user_id"]
    if "is_global" in kwargs:
        is_global = kwargs["is_global"]
    if "tenant_id" in kwargs and tenant_id is None:
        tenant_id = kwargs["tenant_id"]

    tid = tenant_id if tenant_id is not None else 1
    clean_filename = Path(filename).name if filename else "document"
    if is_global:
        return f"tenants/{tid}/global/{clean_filename}"
    uid = user_id if user_id is not None else 0
    return f"tenants/{tid}/personal/{uid}/{clean_filename}"


class BaseStorageProvider(ABC):
    """Abstract base class for enterprise storage engines."""

    @abstractmethod
    def upload_bytes(self, data: bytes, key: str) -> str:
        """Store bytes under key. Returns key."""
        pass

    @abstractmethod
    def upload_file(self, file_path: Union[str, Path], key: str) -> str:
        """Store file from path under key. Returns key."""
        pass

    @abstractmethod
    def download_stream(self, key: str) -> BinaryIO:
        """Retrieve binary stream for object."""
        pass

    @abstractmethod
    def download_bytes(self, key: str) -> bytes:
        """Retrieve raw bytes for object."""
        pass

    @abstractmethod
    def delete_object(self, key: str) -> bool:
        """Delete object under key. Returns True if successfully deleted."""
        pass

    @abstractmethod
    def object_exists(self, key: str) -> bool:
        """Check if object exists under key."""
        pass

    @abstractmethod
    def list_objects(self, prefix: str = "") -> List[str]:
        """List object keys under prefix."""
        pass

    @abstractmethod
    def generate_presigned_put_url(self, key: str, expiry_seconds: int = 3600) -> str:
        """Generate presigned PUT URL for direct browser uploads."""
        pass

    @abstractmethod
    def generate_presigned_get_url(self, key: str, expiry_seconds: int = 3600) -> str:
        """Generate presigned GET URL for secure document access."""
        pass

    def generate_presigned_url(self, key: str, expiration_seconds: int = 3600, method: str = "get_object") -> str:
        """Unified presigned URL generation."""
        if method.lower() in ("put", "put_object"):
            return self.generate_presigned_put_url(key, expiry_seconds=expiration_seconds)
        return self.generate_presigned_get_url(key, expiry_seconds=expiration_seconds)


class LocalStorageProvider(BaseStorageProvider):
    """Filesystem-backed storage provider. Default for single-node / development."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or UPLOAD_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        clean_key = key.lstrip("/\\").replace("..", "")
        return (self.base_dir / clean_key).resolve()

    def upload_bytes(self, data: bytes, key: str) -> str:
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info(f"LocalStorage: saved {len(data)} bytes to {path}")
        return key

    def upload_file(self, file_path: Union[str, Path], key: str) -> str:
        data = Path(file_path).read_bytes()
        return self.upload_bytes(data, key)

    def download_stream(self, key: str) -> BinaryIO:
        path = self._resolve_path(key)
        if not path.exists():
            raise FileNotFoundError(f"LocalStorage: object '{key}' not found at {path}")
        return io.BytesIO(path.read_bytes())

    def download_bytes(self, key: str) -> bytes:
        path = self._resolve_path(key)
        if not path.exists():
            raise FileNotFoundError(f"LocalStorage: object '{key}' not found at {path}")
        return path.read_bytes()

    def delete_object(self, key: str) -> bool:
        path = self._resolve_path(key)
        if path.exists():
            try:
                os.remove(path)
                logger.info(f"LocalStorage: deleted {path}")
                return True
            except Exception as e:
                logger.error(f"LocalStorage: failed to delete {path}: {e}")
                return False
        return False

    def object_exists(self, key: str) -> bool:
        return self._resolve_path(key).exists()

    def list_objects(self, prefix: str = "") -> List[str]:
        clean_prefix = prefix.lstrip("/\\")
        target_dir = self.base_dir / clean_prefix
        if not target_dir.exists():
            return []
        keys = []
        for p in target_dir.rglob("*"):
            if p.is_file():
                keys.append(str(p.relative_to(self.base_dir)).replace("\\", "/"))
        return keys

    def generate_presigned_put_url(self, key: str, expiry_seconds: int = 3600) -> str:
        return "/upload"

    def generate_presigned_get_url(self, key: str, expiry_seconds: int = 3600) -> str:
        return f"/documents/{Path(key).name}/download"


class S3StorageProvider(BaseStorageProvider):
    """
    S3-compatible distributed object storage provider.
    Works seamlessly with AWS S3, MinIO, Cloudflare R2, or Ceph.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        region_name: Optional[str] = None,
        public_endpoint_url: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or S3_ENDPOINT_URL
        self.public_endpoint_url = public_endpoint_url or S3_PUBLIC_ENDPOINT_URL
        self.access_key = access_key or S3_ACCESS_KEY
        self.secret_key = secret_key or S3_SECRET_KEY
        self.bucket_name = bucket_name or S3_BUCKET_NAME
        self.region_name = region_name or S3_REGION

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region_name,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket"):
                try:
                    self.s3_client.create_bucket(Bucket=self.bucket_name)
                    logger.info(f"S3Storage: Created bucket '{self.bucket_name}' on {self.endpoint_url}")
                except Exception as ce:
                    logger.warning(f"Could not auto-create S3 bucket '{self.bucket_name}': {ce}")
            else:
                logger.warning(f"S3 head_bucket check returned {error_code}: {e}")
        except Exception as e:
            logger.warning(f"Unable to connect to S3/MinIO endpoint '{self.endpoint_url}': {e}")

    def upload_bytes(self, data: bytes, key: str) -> str:
        clean_key = key.lstrip("/")
        self._ensure_bucket_exists()
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=clean_key,
            Body=data,
        )
        logger.info(f"S3Storage: uploaded {len(data)} bytes to {self.bucket_name}/{clean_key}")
        return clean_key

    def upload_file(self, file_path: Union[str, Path], key: str) -> str:
        clean_key = key.lstrip("/")
        self._ensure_bucket_exists()
        self.s3_client.upload_file(str(file_path), self.bucket_name, clean_key)
        logger.info(f"S3Storage: uploaded {file_path} to {self.bucket_name}/{clean_key}")
        return clean_key

    def download_stream(self, key: str) -> BinaryIO:
        clean_key = key.lstrip("/")
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=clean_key)
            body = response["Body"]
            return io.BytesIO(body.read())
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise FileNotFoundError(f"S3 object '{clean_key}' not found in bucket '{self.bucket_name}'")
            raise

    def download_bytes(self, key: str) -> bytes:
        stream = self.download_stream(key)
        return stream.read()

    def delete_object(self, key: str) -> bool:
        clean_key = key.lstrip("/")
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=clean_key)
            logger.info(f"S3Storage: deleted {self.bucket_name}/{clean_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete S3 object {clean_key}: {e}")
            return False

    def object_exists(self, key: str) -> bool:
        clean_key = key.lstrip("/")
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except ClientError:
            return False

    def list_objects(self, prefix: str = "") -> List[str]:
        clean_prefix = prefix.lstrip("/")
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            keys = []
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=clean_prefix):
                for item in page.get("Contents", []):
                    keys.append(item["Key"])
            return keys
        except ClientError as e:
            logger.error(f"S3 list_objects error: {e}")
            return []

    def generate_presigned_put_url(self, key: str, expiry_seconds: int = 3600) -> str:
        clean_key = key.lstrip("/")
        url = self.s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket_name, "Key": clean_key},
            ExpiresIn=expiry_seconds,
        )
        if self.public_endpoint_url and self.endpoint_url in url:
            url = url.replace(self.endpoint_url, self.public_endpoint_url, 1)
        return url

    def generate_presigned_get_url(self, key: str, expiry_seconds: int = 3600) -> str:
        clean_key = key.lstrip("/")
        url = self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": clean_key},
            ExpiresIn=expiry_seconds,
        )
        if self.public_endpoint_url and self.endpoint_url in url:
            url = url.replace(self.endpoint_url, self.public_endpoint_url, 1)
        return url


_storage_instance: Optional[BaseStorageProvider] = None


def get_storage_provider(force_reload: bool = False) -> BaseStorageProvider:
    """Return active StorageProvider singleton based on STORAGE_BACKEND."""
    global _storage_instance
    if _storage_instance is None or force_reload:
        if STORAGE_BACKEND == "s3":
            logger.info(f"Initializing S3StorageProvider (MinIO/S3 at {S3_ENDPOINT_URL})")
            _storage_instance = S3StorageProvider()
        else:
            logger.info("Initializing LocalStorageProvider (filesystem-backed)")
            _storage_instance = LocalStorageProvider()
    return _storage_instance
