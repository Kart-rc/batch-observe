# Product Requirements Document: Hook Dispatcher Service

## 1. Executive Summary
The Hook Dispatcher Service is the reliable front-door component of the Batch Post-Write Validation system. It operates as a serverless ingestion and normalization pipeline that detects batch data writes as they land in storage (Delta Lake and S3 Parquet). 

Its core value proposition is enabling **zero-code-change observability** for data engineering teams. By hooking into the storage layer rather than requiring developers to embed SDKs into their Spark or Python jobs, the Hook Dispatcher provides a framework-agnostic trigger mechanism to initiate data quality validation orchestrations via Step Functions.

## 2. Mission
To provide a highly reliable, high-throughput, and extensible event ingestion layer that guarantees exactly-once triggering of batch data validation pipelines without interfering with primary data production workloads.

**Core Principles:**
*   **Reliability First:** Storage events must never be dropped; SQS and Dead Letter Queues (DLQs) act as shock absorbers.
*   **Exactly-Once Processing:** Duplicate storage events must not duplicate compute costs; strict deduplication is required.
*   **Framework Agnostic:** Rely solely on storage-layer exhaust (commit logs, object events) rather than compute-layer SDKs.

## 3. Target Users
*   **Platform Engineers:** Need an observable, scalable infrastructure that handles massive backfills without manual intervention.
*   **Data Engineers:** Need their data validated immediately after it is written, without having to modify their existing Spark, Dask, or Python scripts.
*   **Data Stewards:** Need confidence that validation checks are dependably triggered for every single write to critical tables.

## 4. MVP Scope

### Core Functionality
- [x] Delta Lake Commit Log Polling
- [x] S3 EventBridge Notification Routing (Parquet)
- [x] SQS FIFO Event Buffering
- [x] Event Normalization (Delta/S3 to canonical `ValidationRequest`)
- [x] S3 Parquet Multi-file Batching (Tumbling Window)
- [x] Exactly-Once Deduplication (DynamoDB)
- [x] Step Functions Triggering

### Out of Scope for MVP
- [ ] Apache Iceberg Catalog Listeners (Deferred to Phase 2)
- [ ] Direct Kafka/Kinesis Integration
- [ ] Multi-region active-active deployment

## 5. User Stories
1.  **As a Data Engineer**, I want Delta Lake commits to automatically trigger data validation, so that I don't have to add validation SDKs to my Spark code.
2.  **As a Platform Engineer**, I want the dispatcher to handle a sudden burst of 10,000 backfill writes without crashing, so that the system remains stable during major data rewrites.
3.  **As a Data Steward**, I want S3 Parquet multi-file writes to be evaluated as a single logical batch, so that volume metrics are calculated accurately.
4.  **As a FinOps Analyst**, I want strict deduplication of S3 event notifications, so that we don't pay for redundant Spark/DuckDB validation tasks.

## 6. Core Architecture & Patterns
The Hook Dispatcher follows an **Event-Driven Serverless Architecture** using the **Pipes and Filters** pattern:

*   **Ingestion:** Scheduled Lambdas (Delta) and EventBridge rules (S3) act as event producers.
*   **Buffering:** Amazon SQS FIFO acts as the durable pipe, decoupling ingestion from processing and providing load leveling.
*   **Processing:** A Normalizer Lambda acts as the filter, parsing distinct storage schemas into a standard canonical model.
*   **State:** DynamoDB is used for lightweight, high-performance state management (tracking poller cursors, aggregating windows, and deduplicating).

## 7. Tools/Features
*   **Delta Commit Poller:** A Lambda function triggered by EventBridge (e.g., every 30s) that tracks `last_processed_version` in DynamoDB and pushes raw Delta commit JSONs to SQS.
*   **S3 Event Aggregator:** Logic within the Normalizer Lambda that buffers S3 `ObjectCreated` events in DynamoDB for a 60-second tumbling window to reconstruct complete logical partitions from Spark multi-part writes.
*   **Event Normalizer:** The core mapping logic that translates Delta metadata and aggregated S3 metadata into the `ValidationRequest` schema.
*   **Deduplication Engine:** A generic conditional-write mechanism in DynamoDB based on `dataset_urn` and commit versions/ETags.

## 8. Technology Stack
*   **Compute:** AWS Lambda (Python 3.12)
*   **Messaging:** Amazon SQS FIFO, Amazon EventBridge
*   **Database:** Amazon DynamoDB (On-Demand capacity)
*   **Storage:** Amazon S3 (for Delta logs and Parquet data)
*   **Downstream Integration:** AWS Step Functions (Validation Orchestrator)
*   **IaC:** Terraform or AWS CDK (to be determined by platform standards)

## 9. Security & Configuration
*   **Authentication/Authorization:** Execution via strictly scoped AWS IAM Roles. The Delta Poller needs `s3:ListBucket` and `s3:GetObject` ONLY for `_delta_log/` directories. Target S3 data should remain untouched by this service.
*   **Configuration:** Managed via Environment Variables for Lambda functions (e.g., `SQS_QUEUE_URL`, `DYNAMODB_TABLE_PREFIX`).
*   **Network:** Deployed within the target Data VPC to ensure secure access to S3 Gateway Endpoints and Step Functions without traversing the public internet.

## 10. API Specification (Output Payload)
The service does not expose a REST API. Its sole output is the invocation of a Step Function with the following canonical payload:

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

## 11. Success Criteria
- [x] 100% of tracked Delta commits successfully generate a `ValidationRequest`.
- [x] End-to-end latency from write completion to Step Function trigger is < 60 seconds.
- [x] 0 dropped events during simulated Lambda throttling or cold starts.
- [x] Duplicate S3 events trigger exactly one Step Functions execution.

## 12. Implementation Phases

**Phase 1: Foundation & IaC**
*   **Goal:** Deploy required AWS infrastructure.
*   **Deliverables:**
    - [x] Terraform/CDK for SQS FIFO queues and DLQs.
    - [x] DynamoDB tables (`HookState`, `S3EventBuffer`, `HookDeduplication`).
*   **Validation:** Verify infrastructure deployment and IAM permissions.

**Phase 2: Ingestion Layer**
*   **Goal:** Capture events from S3 and Delta.
*   **Deliverables:**
    - [x] EventBridge rules for S3 Parquet.
    - [x] Delta Commit Poller Lambda with `HookState` management.
*   **Validation:** Confirm raw events flow into the SQS FIFO queue.

**Phase 3: Normalization & Orchestration**
*   **Goal:** Process events and trigger Step Functions.
*   **Deliverables:**
    - [x] Normalizer Lambda function.
    - [x] S3 Parquet tumbling window aggregation logic.
    - [x] DynamoDB-based deduplication logic.
*   **Validation:** End-to-end integration tests confirming exactly-once Step Function invocation.

## 13. Future Considerations
*   **Apache Iceberg Support:** Implementing a catalog-based listener (e.g., AWS Glue API polling or EventBridge events) to map Iceberg snapshot commits to the `ValidationRequest`.
*   **Custom Dispatch Hooks:** Exposing a simple HTTPS endpoint via API Gateway to allow manual trigger injection for ad-hoc validation runs.

## 14. Risks & Mitigations
1.  **Risk:** Massive backfills overwhelm the Normalizer Lambda's concurrent execution limits.
    *   **Mitigation:** SQS FIFO buffer absorbs the spike; Lambda concurrency is explicitly capped to prevent downstream Step/Spark throttling.
2.  **Risk:** Spark Parquet writes take longer than the 60s tumbling window, resulting in fragmented validation.
    *   **Mitigation:** Monitor occurrence rates. If high, implement a "success file" trigger approach (e.g., waiting for `_SUCCESS`) as an optional configuration for slow jobs.
3.  **Risk:** Duplicate Delta commit versions are processed due to Lambda retries.
    *   **Mitigation:** DynamoDB conditional writes using a hash of the commit version and table urn ensure strict idempotency.
