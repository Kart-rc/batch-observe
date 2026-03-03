# Hook Dispatcher Service: Detailed Design

## Overview
This document specifies the design for the Hook Dispatcher Service for the Batch Post-Write Validation system. The chosen architecture is **Approach 1: SQS Event Buffering with Lambda Consumers**.

This service acts as the reliable front door for batch data observability events, normalizing trigger events from Delta Lake (Commit Logs) and S3 (Parquet EventBridge Notifications) into a canonical `ValidationRequest` that triggers the Step Functions Validation Orchestrator.

## Core Directives

1.  **Reliability First:** Every storage event must eventually trigger validation. No dropped events.
2.  **Exactly-Once Processing:** The Hook Dispatcher must guarantee that a unique storage event (e.g., a specific Delta commit version or an aggregated window of S3 Parquet writes) triggers the Step Functions *exactly once*.
3.  **Extensible Normalization:** The system must easily support adding new storage hooks (like Iceberg catalog listeners) with minimal changes to core routing logic.

## Architecture

![Hook Dispatcher Architecture](https://via.placeholder.com/800x400.png?text=Hook+Dispatcher+Architecture)
*(Internal visual placeholder for architecture diagram)*

The system leverages AWS Serverless components to ensure elastic scaling and built-in fault tolerance.

### 1. Ingestion Layer

The Ingestion Layer is responsible for detecting new data writes and pushing raw payloads to the Raw Event Queue.

*   **Delta Commit Poller (Lambda):**
    *   **Trigger:** EventBridge Schedule (e.g., every 30 seconds).
    *   **Logic:** Reads `HookState` from DynamoDB for tracked tables. Lists `_delta_log/` in S3. If new commits exist, it reads the JSON, constructs a raw Delta trigger event, and pushes it to the SQS Raw Event Queue. Updates `HookState`.
*   **S3 Event Notification Listener (EventBridge):**
    *   **Trigger:** S3 `ObjectCreated:*` events matching the `gold/_staging/*.parquet` prefix/suffix.
    *   **Logic:** EventBridge routes the raw S3 event directly to the SQS Raw Event Queue.

### 2. Buffering Layer (SQS)

*   **Raw Event Queue (SQS FIFO):**
    *   Acts as a shock absorber during massive backfills.
    *   Using FIFO ensures ordering (important for Delta commit versions) and provides exactly-once processing guarantees within a 5-minute deduplication window based on `MessageGroupId` and `MessageDeduplicationId`.
    *   *MessageGroupId Strategy:* `dataset_urn`.
    *   *MessageDeduplicationId Strategy:*
        *   Delta: `dataset_urn:commit_version`
        *   S3/Parquet: S3 object `ETag`
*   **Raw Event DLQ:** Captures malformed events or events that consistently fail normalizer processing after maximum receive counts.

### 3. Processing Layer

*   **Event Normalizer (Lambda):**
    *   **Trigger:** SQS Raw Event Queue.
    *   **Logic:**
        1.  **Parse Payload:** Determine the source (Delta vs. S3).
        2.  **S3 Batching (Parquet Only):** If the event is an S3 Parquet file, the normalizer writes the file metadata to the DynamoDB `S3EventBuffer` table. It checks if the tumbling window (e.g., 60 seconds) has closed for that `dataset_urn` and partition. If the window is still open, it stops processing for this event. If the window closes, it aggregates all buffered files into a single batch event.
        3.  **Normalization:** Converts the Delta commit or the aggregated S3 batch into a canonical `ValidationRequest`.
        4.  **Deduplication:** Writes the generated `request_id` (a ULID) to the DynamoDB `HookDeduplication` table with a Conditional Write. If the write fails (duplicate found), the process ends gracefully.
        5.  **Trigger Step Functions:** Starts the Step Functions execution with the `ValidationRequest` payload.

### 4. Storage & State Layer (DynamoDB)

*   **HookState Table:** Tracks the `last_processed_version` for Delta tables to prevent re-reading the entire commit log on every poll.
*   **S3EventBuffer Table:** Temporarily stores S3 object metadata to aggregate multi-part Parquet writes into a single validation request. Uses TTL to automatically expire stale buffers.
*   **HookDeduplication Table:** Ensures exactly-once triggering of the Step Functions. Stores the `ValidationRequest` ID with a 24-hour TTL.

## Data Models

### Canonical ValidationRequest

This is the standard payload passed to the Step Functions Orchestrator.

```json
{
  "request_id": "vr-01HQX1-a7b2c3d4",
  "dataset_urn": "ds://curated/orders_enriched",
  "storage_type": "delta",
  "table_path": "s3://data-lake/gold/_staging/orders/",
  "commit_version": 42,
  "timestamp": "2026-02-15T02:05:45Z",
  "operation": "WRITE",
  "num_records": 1847203,
  "num_files": 12,
  "total_bytes": 485920384,
  "partition_values": { "order_date": "2026-02-15" },
  "engine_info": "Apache-Spark/3.5.1",
  "correlation_id": "txn-a7b2c3d4"
}
```

## Error Handling & Edge Cases

1.  **Lambda Cold Starts / Throttling:** SQS completely mitigates this. If the normalizer is throttled or errors out, SQS automatically retries the message until it succeeds or hits the DLQ.
2.  **Missing S3 Events:** S3 Event Notifications offer at-least-once delivery. If an event is duplicated, the DynamoDB `HookDeduplication` table prevents double-triggering the validation pipeline.
3.  **Parquet Batching Window Edge Case:** If a Spark job takes longer than the 60-second window to write all Parquet files to a partition, the system will trigger multiple `ValidationRequests` for the same partition. *Resolution:* The Step Functions orchestrator handles this by either processing the subset (safe, but potentially triggers volume anomalies) or requiring the orchestrator to pass a final "commit" marker file (deferred to future if needed; the 60s window covers 99% of use cases).
4.  **Delta Log Unreadable:** If the poller cannot read `_delta_log/`, it increments an `error_count` in `HookState`. After 3 consecutive failures, it triggers a PagerDuty alert.

## Testing Plan

1.  **Unit Tests:** Verify the normalizer logic correctly transforms Delta JSON and S3 Event payloads into the canonical format.
2.  **Integration Tests:** Verify exactly-once semantics using LocalStack (SQS -> Lambda -> DynamoDB Deduplication). Verify the Parquet time-window batching logic.
3.  **End-to-End Tests:** Write mock data to an S3 staging bucket and verify Step Functions is triggered automatically.

## Next Steps
This design is ready for implementation. Proceeds to create `plan-feature.md` to break this down into actionable implementation steps.
