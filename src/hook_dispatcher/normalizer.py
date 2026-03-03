import os
import json
import ulid
from typing import Any, Dict, Optional
from datetime import datetime
import boto3

from src.hook_dispatcher.models import ValidationRequest, DeltaCommitEvent
from src.hook_dispatcher.state import StateStore


class Normalizer:
    def __init__(self, state_store: Optional[StateStore] = None, sfn_client=None):
        self.state = state_store or StateStore()
        self.sfn = sfn_client or boto3.client("stepfunctions")
        self.state_machine_arn = os.environ.get("VALIDATION_SFN_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:Validator")
        self.window_seconds = int(os.environ.get("S3_WINDOW_SECONDS", "60"))

    def handle_sqs_event(self, sqs_event: Dict[str, Any]) -> None:
        """Process a batch of SQS messages."""
        for record in sqs_event.get("Records", []):
            try:
                self._process_record(record)
            except Exception as e:
                # Log the exception but depending on SQS config, we might want to re-raise 
                # to trigger DLQ routing. We'll raise to fail the Lambda if it's strictly FIFO.
                print(f"Error processing record {record.get('messageId')}: {e}")
                raise e

    def _process_record(self, sqs_record: Dict[str, Any]) -> None:
        body = json.loads(sqs_record["body"])
        
        # Determine event type
        if "detail-type" in body and body["detail-type"] == "Object Created":
            # This is an EventBridge S3 Notification
            self._handle_s3_event(body)
        elif "commitInfo" in body:
            # This is our custom Delta Poller event
            self._handle_delta_event(body)
        else:
            print(f"Unknown event format: {json.dumps(body)[:200]}")

    def _handle_delta_event(self, delta_event: Dict[str, Any]) -> None:
        """Map Delta JSON directly to a ValidationRequest."""
        commit = DeltaCommitEvent(**delta_event)
        if not commit.commitInfo or not commit.add:
            return  # Skip if it's just metaData or protocol changes without adds
            
        dataset_urn = delta_event.get("dataset_urn", "unknown")
        table_path = delta_event.get("table_path", "unknown")
        version = delta_event.get("commit_version", 0)
        
        req = ValidationRequest(
            request_id=f"vr-delta-{dataset_urn}-{version}-{ulid.new()}",
            dataset_urn=dataset_urn,
            storage_type="delta",
            table_path=table_path,
            commit_version=version,
            timestamp=datetime.fromtimestamp(commit.commitInfo.timestamp / 1000.0),
            operation=commit.commitInfo.operation,
            num_records=int(commit.commitInfo.operationMetrics.get("numOutputRows", 0)) if commit.commitInfo.operationMetrics else None,
            num_files=int(commit.commitInfo.operationMetrics.get("numFiles", 1)) if commit.commitInfo.operationMetrics else 1,
            total_bytes=commit.add.size,
            partition_values=delta_event.get("partition_values", {}), # Injected by poller
            engine_info=commit.commitInfo.engineInfo,
            correlation_id=commit.commitInfo.txnId
        )
        self._dispatch(req)

    def _handle_s3_event(self, s3_event: Dict[str, Any]) -> None:
        """Buffer S3 event. If window closed, generate ValidationRequest."""
        detail = s3_event["detail"]
        bucket = detail["bucket"]["name"]
        key = detail["object"]["key"]
        
        # Heuristic to find urn and partition. In reality, requires a registry lookup or standard path mapping.
        # e.g. gold/_staging/orders/order_date=2026-02-15/part-xxxxx.parquet
        parts = key.split("/")
        dataset_urn = f"ds://data/{parts[2]}" if len(parts) > 2 else "unknown"
        partition = parts[-2] if "=" in parts[-2] else "default"
        
        buffer_key = f"{dataset_urn}:{partition}"
        
        file_info = {
            "key": key,
            "size": detail["object"]["size"],
            "etag": detail["object"]["etag"],
            "timestamp": s3_event["time"]
        }
        
        self.state.append_to_buffer(buffer_key, file_info, window_ttl_seconds=300)
        
        # Check window
        buffer = self.state.get_buffer(buffer_key)
        if buffer and buffer.age_seconds >= self.window_seconds:
            # Flush
            req_id = f"vr-s3-{buffer_key}-{ulid.new()}"
            req = ValidationRequest(
                request_id=req_id,
                dataset_urn=dataset_urn,
                storage_type="parquet",
                table_path=f"s3://{bucket}/{'/'.join(parts[:-1])}/",
                commit_version=None,
                timestamp=datetime.fromisoformat(file_info["timestamp"].replace("Z", "+00:00")),
                operation="WRITE",
                num_records=None,
                num_files=len(buffer.files),
                total_bytes=sum(f["size"] for f in buffer.files),
                partition_values={partition.split("=")[0]: partition.split("=")[1]} if "=" in partition else {},
                engine_info=None,
                correlation_id=None
            )
            # In a real system, we'd also delete/clear the buffer here using self.state.delete_buffer(buffer_key)
            self._dispatch(req)

    def _dispatch(self, req: ValidationRequest) -> None:
        """Deduplicate and trigger Step Functions."""
        # The deduplication key avoids double-triggering SFN if Lambda retries SQS message
        dedup_key = f"{req.dataset_urn}:{req.commit_version or req.request_id[-10:]}"
        
        if self.state.is_duplicate(dedup_key):
            print(f"Duplicate validation request detected for {dedup_key}. Skipping.")
            return
            
        print(f"Dispatching validation for {req.dataset_urn}")
        self.sfn.start_execution(
            stateMachineArn=self.state_machine_arn,
            name=str(ulid.new()),
            input=req.model_dump_json()
        )

def lambda_handler(event, context):
    normalizer = Normalizer()
    normalizer.handle_sqs_event(event)
    return {"statusCode": 200, "body": "Success"}
