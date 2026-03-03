import time
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError


class S3Buffer:
    def __init__(self, buffer_key: str, files: List[Dict[str, Any]], window_start: int):
        self.buffer_key = buffer_key
        self.files = files
        self.window_start = window_start

    @property
    def age_seconds(self) -> int:
        return int(time.time()) - self.window_start


class StateStore:
    def __init__(self, dynamodb_client=None):
        self.dynamodb = dynamodb_client or boto3.client("dynamodb")
        self.dedup_table = "HookDeduplication"
        self.state_table = "HookState"
        self.buffer_table = "S3EventBuffer"

    def is_duplicate(self, request_id: str, ttl_hours: int = 24) -> bool:
        """
        Attempts to write the request_id. Returns True if it already exists (duplicate),
        False if it was successfully written (new request).
        """
        now = int(time.time())
        ttl = now + (ttl_hours * 3600)
        try:
            self.dynamodb.put_item(
                TableName=self.dedup_table,
                Item={
                    "request_id": {"S": request_id},
                    "created_at": {"N": str(now)},
                    "ttl": {"N": str(ttl)},
                },
                ConditionExpression="attribute_not_exists(request_id)",
            )
            return False
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return True
            raise e

    def get_last_processed_version(self, dataset_urn: str) -> int:
        """Gets the last processed version for a dataset, defaults to -1."""
        response = self.dynamodb.get_item(
            TableName=self.state_table,
            Key={"dataset_urn": {"S": dataset_urn}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return -1
        return int(item.get("last_processed_version", {"N": "-1"})["N"])

    def update_last_processed_version(self, dataset_urn: str, version: int) -> None:
        """Updates the last processed version."""
        self.dynamodb.put_item(
            TableName=self.state_table,
            Item={
                "dataset_urn": {"S": dataset_urn},
                "last_processed_version": {"N": str(version)},
                "updated_at": {"N": str(int(time.time()))},
            },
        )

    def append_to_buffer(
        self, buffer_key: str, file_info: Dict[str, Any], window_ttl_seconds: int = 300
    ) -> None:
        """Appends an S3 event file to the buffer logic using DynamoDB."""
        # For a production scenario this would ideally use Redis or DynamoDB UpdateItem 
        # with list_append, but here we'll do a simple get/update using python for MVP.
        now = int(time.time())
        
        try:
            # Try to create a new buffer entry
            self.dynamodb.put_item(
                TableName=self.buffer_table,
                Item={
                    "buffer_key": {"S": buffer_key},
                    "files": {"S": str([file_info])},  # Storing as stringified list for simplicity
                    "window_start": {"N": str(now)},
                    "ttl": {"N": str(now + window_ttl_seconds)},
                },
                ConditionExpression="attribute_not_exists(buffer_key)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Entry exists, read and append
                # Note: In high currency, optimistic locking or list_append should be used.
                # For this basic implementation we will use a naive read-modify-write.
                resp = self.dynamodb.get_item(
                    TableName=self.buffer_table, Key={"buffer_key": {"S": buffer_key}}
                )
                if "Item" in resp:
                    item_files_str = resp["Item"]["files"]["S"]
                    import ast
                    try:
                        files = ast.literal_eval(item_files_str)
                    except Exception:
                        files = []
                        
                    files.append(file_info)
                    
                    self.dynamodb.update_item(
                        TableName=self.buffer_table,
                        Key={"buffer_key": {"S": buffer_key}},
                        UpdateExpression="SET files = :val",
                        ExpressionAttributeValues={":val": {"S": str(files)}}
                    )
            else:
                raise e

    def get_buffer(self, buffer_key: str) -> Optional[S3Buffer]:
        """Reads the S3 buffer."""
        response = self.dynamodb.get_item(
            TableName=self.buffer_table, Key={"buffer_key": {"S": buffer_key}}
        )
        item = response.get("Item")
        if not item:
            return None
            
        import ast
        try:
            files = ast.literal_eval(item["files"]["S"])
        except Exception:
            files = []
            
        return S3Buffer(
            buffer_key=buffer_key,
            files=files,
            window_start=int(item["window_start"]["N"]),
        )
