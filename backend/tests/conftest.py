import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("TABLE_NAME", "mediamaster-test")
os.environ.setdefault("USER_POOL_ID", "us-east-1_TEST")
os.environ.setdefault("USER_POOL_CLIENT_ID", "testclient")

from mediamaster_api import db  # noqa: E402
from mediamaster_api.auth import current_uid, jwt_only_uid  # noqa: E402
from mediamaster_api.main import app  # noqa: E402

TEST_UID = "test-user"


@pytest.fixture()
def table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=os.environ["TABLE_NAME"],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        db._table = None  # force re-resolve inside the moto context
        yield
        db._table = None


@pytest.fixture()
def client(table):
    app.dependency_overrides[current_uid] = lambda: TEST_UID
    app.dependency_overrides[jwt_only_uid] = lambda: TEST_UID
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
