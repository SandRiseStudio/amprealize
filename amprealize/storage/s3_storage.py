"""S3-compatible storage adapter for cloud deployments.

Provides unified interface for storing JSON data, artifacts, and telemetry files
in S3, MinIO, or other S3-compatible object storage systems.

Supports multi-environment configuration:
- Local development: MinIO (http://localhost:9000)
- Staging: AWS S3 with staging bucket
- Production: AWS S3 with production bucket + lifecycle policies

Behaviors referenced:
- behavior_align_storage_layers: Provider abstraction for local/cloud switching
- behavior_externalize_configuration: Bucket names and endpoints from settings
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# Import settings for multi-environment configuration
try:
    from amprealize.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


class S3JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles UUID and datetime objects."""

    def default(self, o: Any) -> Any:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


class S3Storage:
    """S3-compatible storage adapter with automatic settings integration."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint: Optional[str] = None,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        """Initialize S3 storage client.

        Args:
            bucket: S3 bucket name (default: from settings.storage.s3_bucket)
            endpoint: S3 endpoint URL (default: from settings or AWS default)
            region: AWS region (default: from settings or us-east-1)
            aws_access_key_id: AWS access key (default: from settings or env)
            aws_secret_access_key: AWS secret key (default: from settings or env)

        Raises:
            ImportError: If boto3 is not installed
            ValueError: If bucket is not configured
        """
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for S3Storage. Install with: pip install boto3"
            )

        # Resolve configuration from settings or parameters
        if SETTINGS_AVAILABLE and bucket is None:
            self.bucket = settings.storage.s3_bucket  # type: ignore[possibly-unbound]
            self.endpoint = endpoint or settings.storage.s3_endpoint  # type: ignore[possibly-unbound]
            self.region = region or settings.storage.s3_region  # type: ignore[possibly-unbound]
            aws_access_key_id = aws_access_key_id or settings.storage.aws_access_key_id  # type: ignore[possibly-unbound]
            aws_secret_access_key = aws_secret_access_key or settings.storage.aws_secret_access_key  # type: ignore[possibly-unbound]
        else:
            self.bucket = bucket
            self.endpoint = endpoint
            self.region = region or "us-east-1"

        if not self.bucket:
            raise ValueError(
                "S3Storage requires bucket parameter or settings module with "
                "STORAGE__S3_BUCKET configured"
            )

        # Initialize boto3 S3 client
        client_kwargs: Dict[str, Any] = {
            "region_name": self.region,
        }

        if self.endpoint:
            # MinIO or custom S3-compatible endpoint
            client_kwargs["endpoint_url"] = self.endpoint

        if aws_access_key_id and aws_secret_access_key:
            # Explicit credentials (for local MinIO or testing)
            client_kwargs["aws_access_key_id"] = aws_access_key_id
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key
        # Otherwise, boto3 will use IAM role or ~/.aws/credentials

        self.s3 = boto3.client("s3", **client_kwargs)

    def put_json(self, key: str, data: Dict[str, Any], *, metadata: Optional[Dict[str, str]] = None) -> None:
        """Store JSON data in S3.

        Args:
            key: S3 object key (path within bucket)
            data: Dictionary to store as JSON
            metadata: Optional S3 object metadata

        Raises:
            ClientError: If S3 operation fails
        """
        body = json.dumps(data, cls=S3JSONEncoder, indent=2)

        put_kwargs: Dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": "application/json",
        }

        if metadata:
            put_kwargs["Metadata"] = metadata

        self.s3.put_object(**put_kwargs)

    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve JSON data from S3.

        Args:
            key: S3 object key

        Returns:
            Parsed JSON dict or None if object doesn't exist

        Raises:
            ClientError: If S3 operation fails (except 404)
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def list_keys(self, prefix: str = "", max_keys: int = 1000) -> List[str]:
        """List object keys with optional prefix filter.

        Args:
            prefix: Filter keys by prefix (e.g., "telemetry/2025-11/")
            max_keys: Maximum number of keys to return

        Returns:
            List of object keys matching prefix
        """
        response = self.s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        if "Contents" not in response:
            return []

        return [obj["Key"] for obj in response["Contents"]]

    def delete(self, key: str) -> bool:
        """Delete an object from S3.

        Args:
            key: S3 object key

        Returns:
            True if deleted, False if object didn't exist
        """
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return False
            raise

    def exists(self, key: str) -> bool:
        """Check if an object exists in S3.

        Args:
            key: S3 object key

        Returns:
            True if object exists, False otherwise
        """
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def put_file(self, key: str, file_path: str, *, metadata: Optional[Dict[str, str]] = None) -> None:
        """Upload a file to S3.

        Args:
            key: S3 object key (destination path)
            file_path: Local file path to upload
            metadata: Optional S3 object metadata
        """
        extra_args = {}
        if metadata:
            extra_args["Metadata"] = metadata

        self.s3.upload_file(file_path, self.bucket, key, ExtraArgs=extra_args)

    def get_file(self, key: str, file_path: str) -> None:
        """Download a file from S3.

        Args:
            key: S3 object key (source path)
            file_path: Local file path to save to
        """
        self.s3.download_file(self.bucket, key, file_path)

    def get_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """Generate a presigned URL for temporary object access.

        Args:
            key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL string
        """
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expiration,
        )
