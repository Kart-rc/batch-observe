# Feature: Hook Dispatcher Service

The following plan should be complete, but its important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils types and models. Import from the right files etc.

## Feature Description

The Hook Dispatcher Service is the reliable front-door component of the Batch Post-Write Validation system. It operates as a serverless ingestion and normalization pipeline that detects batch data writes as they land in storage (Delta Lake and S3 Parquet). It normalizes raw Delta commit logs and S3 Event Notifications into a canonical `ValidationRequest` that triggers the Step Functions Validation Orchestrator. SQS FIFO buffers events to protect against massive bursts, and DynamoDB is used for exact-once deduplication and S3 Parquet multi-file grouping.

## User Story

As a Platform Engineer
I want a serverless ingestion service to detect new data writes and trigger validation jobs 
So that I don't need to ask data engineers to modify their existing Spark code, and my validation architecture remains totally decoupled from compute engines.

## Problem Statement

Batch data pipelines span many compute frameworks (Spark, Dask, standard Python, Glue, etc). Embedding SDKs inside each of these engines for data validation causes high adoption friction and upgrade pain. We need a way to trigger validation asynchronously *after* data lands in storage, without dropping events during backfill spikes or duplicating work.

## Solution Statement

We build a serverless Hook Dispatcher:
1. S3 EventBridge rules automatically push Parquet write notifications to an SQS FIFO Queue.
2. A Scheduled Lambda (Delta Poller) polls `_delta_log/` for table commits and pushes them to the same SQS FIFO Queue.
3. A Normalizer Lambda consumes from the SQS queue. For Delta, it maps the commit. For S3, it buffers in DynamoDB for 60 seconds to group multi-part writes, then maps them. 
4. The Normalizer writes the generated `request_id` to DynamoDB (conditional write) to ensure exactly-once execution before starting the Validation Step Functions.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: High
**Primary Systems Affected**: AWS Serverless infrastructure, Batch pipelines
**Dependencies**: `uv` for python dependencies, `boto3`, `ulid-py`

---

## CONTEXT REFERENCES

### Relevant Codebase Files IMPORTANT: YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

- `docs/plans/2026-03-02-hook-dispatcher-design.md` - Why: Contains the detailed design choices and architecture outline.
- `docs/plans/2026-03-02-hook-dispatcher-prd.md` - Why: Contains the product goals, scope, and target success criteria.
- `docs/batch_postwrite_validation_lld_v1.md` - Why: Contains specific payload examples and internal algorithms (like the 60s tumbling window logic).

### New Files to Create

- `src/hook_dispatcher/__init__.py`
- `src/hook_dispatcher/models.py` - Pydantic models for `ValidationRequest` and storage events.
- `src/hook_dispatcher/delta_poller.py` - Lambda handler for polling delta logs.
- `src/hook_dispatcher/normalizer.py` - Lambda handler for processing the SQS queue.
- `src/hook_dispatcher/state.py` - DynamoDB state interactions (buffer, map, deduplicate).
- `tests/hook_dispatcher/test_normalizer.py` - Unit tests.
- `infrastructure/terraform/hook_dispatcher/main.tf` - Placeholder/Actual IaC for queues, DBs, and Lambdas.

### Relevant Documentation YOU SHOULD READ THESE BEFORE IMPLEMENTING!

- [AWS boto3 SQS docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs.html)
- [AWS boto3 DynamoDB docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html)
- Python `uv` package manager documentation (for building and testing).

### Patterns to Follow

**Naming Conventions:**
- Use snake_case for Python variables and functions.
- Use PascalCase for Classes and Pydantic models.
- Group Lambda Handlers in easily identifiable entrypoints (e.g., `def handler(event, context):`).

**Error Handling:**
- DynamoDB `ConditionalCheckFailedException` should be caught gracefully as indicating a duplicate request, NOT an error that fails the SQS message.
- S3 / Delta payload parsing errors should be logged with context and potentially pushed to a DLQ if unrecoverable.

---

## IMPLEMENTATION PLAN

### Phase 1: Foundation

Set up the project structure with `uv`.

**Tasks:**
- Initialize python application structure if not done.
- Define `pyproject.toml` dependencies (e.g., `boto3`, `pydantic`, `ulid-py`, `pytest`).
- Create empty data models (`ValidationRequest`, etc.) in `models.py`.
- Define DynamoDB state interfaces in `state.py`.

### Phase 2: Core Implementation

Implement the application logic.

**Tasks:**
- Implement `state.py` methods for Deduplication, HookState tracking, and S3EventBuffer tumbling windows.
- Implement the `normalizer.py` Lambda to handle SQS generic events, route Delta vs S3, and trigger Step Functions.
- Implement the `delta_poller.py` Lambda to safely read S3 directories, track versions, and emit to SQS.

### Phase 3: Integration

Connect to existing routing schemas.

**Tasks:**
- Add standard AWS Lambda handlers that can be referenced by the IaC (Terraform).
- Stub out the AWS Step Functions client code within the normalizer.

### Phase 4: Testing & Validation

Prove the system works.

**Tasks:**
- Add unit tests for `ValidationRequest` generation.
- Mock boto3 `dynamodb`, `sqs`, and `sfn` responses and test `normalizer.py`.
- Ensure duplicate requests via DynamoDB Conditional Checks silently skip duplicate `sfn` calls.

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order, top to bottom. Each task is atomic and independently testable.

### CREATE `pyproject.toml`

- **IMPLEMENT**: Use `uv add boto3 pydantic ulid-py` to set up dependencies. Add `pytest moto pytest-cov` to dev dependencies.
- **VALIDATE**: `uv sync`

### CREATE `src/hook_dispatcher/models.py`

- **IMPLEMENT**: Define Pydantic models: `ValidationRequest` (refer to HLD exact schema), `S3Event`, `DeltaCommitEvent`.
- **VALIDATE**: `uv run python -c "from hook_dispatcher.models import ValidationRequest"`

### CREATE `src/hook_dispatcher/state.py`

- **IMPLEMENT**: Create `StateStore` class wrapping `boto3.client('dynamodb')`. Implement `is_duplicate(request_id)`, `get_last_processed_version(urn)`, `update_last_processed_version(urn, v)`, and `buffer_s3_event(...)`.
- **IMPORTS**: `boto3`, `time`, `typing`
- **VALIDATE**: `uv run python -m py_compile src/hook_dispatcher/state.py`

### CREATE `src/hook_dispatcher/normalizer.py`

- **IMPLEMENT**: Implement the SQS event consumer. Parse records, switch on event type (S3 vs Delta). For S3, apply tumbling window via `state.py`. For Delta, map directly. Deduplicate via `state.py`. Trigger `sfn.start_execution`.
- **IMPORTS**: `json`, `boto3`, `ulid`, `src.hook_dispatcher.models`, `src.hook_dispatcher.state`
- **GOTCHA**: Ensure exceptions inside the record loop don't silently swallow errors or immediately crash the whole batch if partial batch failure is configurable (though for SQS Standard, exception fails the batch; for SQS FIFO, batch failure blocks the queue—handle gracefully).
- **VALIDATE**: `uv run python -m py_compile src/hook_dispatcher/normalizer.py`

### CREATE `src/hook_dispatcher/delta_poller.py`

- **IMPLEMENT**: Implement EventBridge Lambda handler. Query `state.py` for last version. Read `s3.list_objects_v2` for `_delta_log/`. Post new commits to SQS.
- **VALIDATE**: `uv run python -m py_compile src/hook_dispatcher/delta_poller.py`

### CREATE `tests/hook_dispatcher/test_normalizer.py`

- **IMPLEMENT**: Write unit tests using `pytest` and `moto` to simulate SQS events and verify that `sfn.start_execution` is triggered precisely once for duplicate inputs.
- **VALIDATE**: `uv run pytest tests/hook_dispatcher/test_normalizer.py`

---

## TESTING STRATEGY

### Unit Tests
- Use `pytest`.
- Use `moto` to mock AWS services: S3, SQS, DynamoDB, Step Functions.
- Verify normalizer behavior when S3 tumbling window is OPEN vs CLOSED.
- Verify normalizer skips execution if `is_duplicate` returns True.

### Integration Tests
- Test combining the delta poller reading mocked S3 objects and successfully publishing to a mocked SQS queue.

### Edge Cases
- Throttled DynamoDB writes.
- Malformed SQS JSON payloads.
- S3 batch contains files belonging to different partitions (routing correctness).

---

## VALIDATION COMMANDS

Execute every command to ensure zero regressions and 100% feature correctness.

### Level 1: Syntax & Style

`uv run ruff check src/ tests/`
`uv run ruff format --check src/ tests/`

### Level 2: Unit Tests

`uv run pytest tests/ -v`

### Level 3: Manual Validation

(No direct UI manual validation possible as this is backend AWS logic. Verify `pytest` covers the Boto3 mocks extensively).

---

## ACCEPTANCE CRITERIA

- [ ] `ValidationRequest` model matches the PRD precisely.
- [ ] `uv pytest` executes completely, testing deduplication and grouping logic.
- [ ] DynamoDB `ConditionalCheckFailedException` does NOT cause the SQS event to be returned to the queue (it marks it as a successful consumer ACK).
- [ ] Code is formatted and linted via `ruff`.
- [ ] No regressions in existing functionality (this is a greenfield module, so standard setup applies).

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed immediately
- [ ] All validation commands executed successfully
- [ ] Full test suite passes (unit + integration)
- [ ] No linting or type checking errors
- [ ] Acceptance criteria all met

---

## NOTES
- For Phase 1 of this repository, we heavily mock AWS services with `moto`. Actual infrastructure deployment (Terraform/CDK) will be a subsequent operational task outside the immediate python implementations.
