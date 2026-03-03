import json
import pytest
import boto3
from moto import mock_aws
from src.hook_dispatcher.state import StateStore
from src.hook_dispatcher.normalizer import Normalizer


@pytest.fixture
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    import os
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def mock_dynamodb(aws_credentials):
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="HookDeduplication",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "request_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )
        dynamodb.create_table(
            TableName="HookState",
            KeySchema=[{"AttributeName": "dataset_urn", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "dataset_urn", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )
        dynamodb.create_table(
            TableName="S3EventBuffer",
            KeySchema=[{"AttributeName": "buffer_key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "buffer_key", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )
        yield dynamodb


@pytest.fixture
def mock_sfn(aws_credentials):
    with mock_aws():
        sfn = boto3.client("stepfunctions", region_name="us-east-1")
        # Create a dummy state machine
        role_arn = "arn:aws:iam::123456789012:role/SFNRole"
        try:
            iam = boto3.client("iam", region_name="us-east-1")
            iam.create_role(
                RoleName="SFNRole",
                AssumeRolePolicyDocument="{}"
            )
        except Exception:
            pass
            
        resp = sfn.create_state_machine(
            name="Validator",
            definition=json.dumps({"StartAt": "Pass", "States": {"Pass": {"Type": "Pass", "End": True}}}),
            roleArn=role_arn
        )
        yield {"client": sfn, "arn": resp["stateMachineArn"]}


def test_delta_event_execution(mock_dynamodb, mock_sfn):
    state = StateStore(mock_dynamodb)
    normalizer = Normalizer(state_store=state, sfn_client=mock_sfn["client"])
    normalizer.state_machine_arn = mock_sfn["arn"]

    delta_event = {
        "dataset_urn": "ds://test/dataset",
        "table_path": "s3://bucket/path",
        "commit_version": 1,
        "commitInfo": {
            "timestamp": 1672531200000,
            "operation": "WRITE",
            "operationMetrics": {"numOutputRows": "100", "numFiles": "1"}
        },
        "add": {"path": "part-001.parquet", "size": 1024, "dataChange": True, "modificationTime": 1672531200000}
    }
    
    sqs_event = {
        "Records": [{"body": json.dumps(delta_event)}]
    }

    # First execution should succeed and call SFN
    normalizer.handle_sqs_event(sqs_event)
    
    # Check SFN executions
    executions = mock_sfn["client"].list_executions(stateMachineArn=mock_sfn["arn"])
    assert len(executions["executions"]) == 1

    # Second execution (duplicate SQS message) should be skipped
    normalizer.handle_sqs_event(sqs_event)
    
    executions = mock_sfn["client"].list_executions(stateMachineArn=mock_sfn["arn"])
    # Should still be 1 because it's deduplicated
    assert len(executions["executions"]) == 1
