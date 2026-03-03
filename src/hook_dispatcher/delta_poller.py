import os
import json
import boto3

from src.hook_dispatcher.state import StateStore


class DeltaPoller:
    def __init__(self, state_store=None, s3_client=None, sqs_client=None):
        self.state = state_store or StateStore()
        self.s3 = s3_client or boto3.client("s3")
        self.sqs = sqs_client or boto3.client("sqs")
        self.queue_url = os.environ.get("TARGET_SQS_URL", "https://sqs.us-east-1.amazonaws.com/123/ValidationQueue.fifo")
        
        # Hardcoding the polling list for this MVP
        self.datasets = [
            {
                "urn": "ds://curated/orders_enriched",
                "bucket": "data-lake",
                "prefix": "gold/_staging/orders/",
                "partition_key": "order_date",
                "partition_value": "2026-02-15" # Mocking partition mapping for now
            }
        ]

    def poll_all(self):
        for dataset in self.datasets:
            self._poll_dataset(dataset)

    def _poll_dataset(self, dataset):
        last_version = self.state.get_last_processed_version(dataset["urn"])
        
        # List _delta_log/ directory
        delta_log_prefix = f"{dataset['prefix']}_delta_log/"
        response = self.s3.list_objects_v2(
            Bucket=dataset["bucket"],
            Prefix=delta_log_prefix
        )
        
        highest_version = last_version
        
        # In Delta, commits are zero-padded 20 digit numbers: e.g. 00000000000000000000.json
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
                
            filename = key.split("/")[-1]
            try:
                version = int(filename.replace(".json", ""))
            except ValueError:
                continue
                
            if version > last_version:
                print(f"Discovered new Delta commit version {version} for {dataset['urn']}")
                self._process_commit(dataset, version, key)
                highest_version = max(highest_version, version)
                
        if highest_version > last_version:
            self.state.update_last_processed_version(dataset["urn"], highest_version)

    def _process_commit(self, dataset, version, s3_key):
        """Read the delta log json, extract add/commitInfo, and send to SQS."""
        resp = self.s3.get_object(Bucket=dataset["bucket"], Key=s3_key)
        content = resp["Body"].read().decode("utf-8")
        
        # Delta commits are JSON-lines
        commit_info = None
        add_action = None
        
        for line in content.splitlines():
            if not line.strip():
                continue
            action = json.loads(line)
            if "commitInfo" in action:
                commit_info = action["commitInfo"]
            elif "add" in action:
                add_action = action["add"]
                
        if commit_info and add_action:
            event_payload = {
                "dataset_urn": dataset["urn"],
                "table_path": f"s3://{dataset['bucket']}/{dataset['prefix']}",
                "commit_version": version,
                "commitInfo": commit_info,
                "add": add_action,
                "partition_values": {dataset["partition_key"]: dataset["partition_value"]}
            }
            
            # Send to SQS FIFO
            self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(event_payload),
                MessageGroupId=dataset["urn"],
                MessageDeduplicationId=f"{dataset['urn']}-{version}"
            )


def lambda_handler(event, context):
    poller = DeltaPoller()
    poller.poll_all()
    return {"statusCode": 200, "body": "Success"}
