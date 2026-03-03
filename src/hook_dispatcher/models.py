from datetime import datetime
from typing import Dict, Optional, List, Any
from pydantic import BaseModel, ConfigDict


class ValidationRequest(BaseModel):
    """Canonical, storage-agnostic request for the Validation Service."""
    request_id: str                     # ULID: "vr-01HQX1-a7b2c3d4"
    dataset_urn: str                    # "ds://curated/orders_enriched"
    storage_type: str                   # "delta" | "parquet"
    table_path: str                     # "s3://data-lake/gold/_staging/orders/"
    commit_version: Optional[int]       # 42 (Delta) or None (Parquet)
    timestamp: datetime                 # When the write completed
    operation: str                      # "WRITE" | "MERGE" | "OVERWRITE" | "APPEND"
    num_records: Optional[int]          # From commit metadata (Delta) or None (Parquet)
    num_files: int                      # Files in this commit/write
    total_bytes: int                    # Total size of committed data
    partition_values: Dict[str, str]    # {"order_date": "2026-02-15"}
    engine_info: Optional[str]          # "Apache-Spark/3.5.1" (from Delta commit)
    correlation_id: Optional[str]       # dag_run_id, txnId, or None

    model_config = ConfigDict(extra="ignore")


class S3Object(BaseModel):
    key: str
    size: int
    etag: str
    versionId: Optional[str] = None
    sequencer: Optional[str] = None


class S3Bucket(BaseModel):
    name: str
    ownerIdentity: Optional[Dict[str, str]] = None
    arn: str


class S3EventDetail(BaseModel):
    s3SchemaVersion: str
    configurationId: str
    bucket: S3Bucket
    object: S3Object


class S3EventRecord(BaseModel):
    eventVersion: str
    eventSource: str
    awsRegion: str
    eventTime: datetime
    eventName: str
    userIdentity: Dict[str, str]
    requestParameters: Dict[str, str]
    responseElements: Dict[str, str]
    s3: S3EventDetail


class S3Event(BaseModel):
    """EventBridge / SQS S3 Notification Event."""
    Records: List[S3EventRecord]


class DeltaAddAction(BaseModel):
    path: str
    size: int
    modificationTime: int
    dataChange: bool
    stats: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class DeltaCommitInfo(BaseModel):
    timestamp: int
    operation: str
    operationParameters: Optional[Dict[str, Any]] = None
    operationMetrics: Optional[Dict[str, str]] = None
    engineInfo: Optional[str] = None
    txnId: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class DeltaCommitEvent(BaseModel):
    """Internal model for parsed Delta limit json lines."""
    commitInfo: Optional[DeltaCommitInfo] = None
    add: Optional[DeltaAddAction] = None
    # We ignore others like 'remove', 'protocol', 'metaData' for the normalizer
    
    model_config = ConfigDict(extra="ignore")
