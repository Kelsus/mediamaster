"""Local UI-dev server: FastAPI on :8000 with moto-mocked DynamoDB, auth
bypassed, and a seeded sample board. No AWS needed.

    cd backend && uv run python ../scripts/local_mock.py

Then in the Vite app set localStorage.setItem('mm.devBypass', '1') and reload.
"""

import os

os.environ["TABLE_NAME"] = "mediamaster-local"
os.environ["USER_POOL_ID"] = "us-east-1_LOCAL"
os.environ["USER_POOL_CLIENT_ID"] = "local"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "local"
os.environ["AWS_SECRET_ACCESS_KEY"] = "local"

from moto import mock_aws  # noqa: E402

mock = mock_aws()
mock.start()

import boto3  # noqa: E402

boto3.client("dynamodb").create_table(
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

from mediamaster_api import db  # noqa: E402
from mediamaster_api.auth import current_uid, jwt_only_uid  # noqa: E402
from mediamaster_api.main import app  # noqa: E402
from mediamaster_api.models import ShowCreate, ShowPatch, Status  # noqa: E402

UID = "local-dev"
app.dependency_overrides[current_uid] = lambda: UID
app.dependency_overrides[jwt_only_uid] = lambda: UID

SEED = [
    # (name, type, service, source, status, rating)
    ("Severance", "tv", "Apple TV+", "Maria", "done", 3),
    ("The Bear", "tv", "Hulu", "Maria", "done", 3),
    ("Slow Horses", "tv", "Apple TV+", "Maria", "done", 2),
    ("Dune: Part Two", "movie", "Max", "Reddit", "done", 2),
    ("Rebel Moon", "movie", "Netflix", "Netflix ads", "poubelle", None),
    ("Citadel", "tv", "Prime", "Netflix ads", "poubelle", None),
    ("The Idol", "tv", "Max", "Twitter", "poubelle", None),
    ("Poor Things", "movie", "Hulu", "Alex", "done", 1),
    ("Shogun", "tv", "Hulu", "Alex", "done", 2),
    ("3 Body Problem", "tv", "Netflix", "Reddit", "watching", None),
    ("Fallout", "tv", "Prime", None, "watching", None),
    # queue — scoring should visibly reorder these
    ("Pachinko", "tv", "Apple TV+", "Maria", "to_watch", None),
    ("The Zone of Interest", "movie", "Max", "Alex", "to_watch", None),
    ("Mrs. Davis", "tv", "Peacock", "Twitter", "to_watch", None),
    ("Killers of the Flower Moon", "movie", "Apple TV+", None, "to_watch", None),
    ("Blue Eye Samurai", "tv", "Netflix", "Reddit", "to_watch", None),
    ("Night Agent", "tv", "Netflix", "Netflix ads", "to_watch", None),
    ("Past Lives", "movie", None, "Maria", "to_watch", None),
    ("The Curse", "tv", "Showtime", None, "to_watch", None),
]

for name, show_type, service, source, status, rating in SEED:
    db.create_show(
        UID,
        ShowCreate(name=name, show_type=show_type, service=service, source=source,
                   status=Status(status), rating=rating),
    )

extra = int(os.environ.get("MOCK_SCALE", "0"))
if extra:
    from mediamaster_api.rank import evenly_spaced

    for i, r in enumerate(evenly_spaced(extra)):
        db.create_show(UID, ShowCreate(name=f"Filler Show {i:03d}", show_type="tv",
                                       rank=r, status=Status.to_watch))
    print(f"Scale mode: +{extra} filler cards in to_watch")

print(f"Seeded {len(SEED)} shows for uid '{UID}'")

import uvicorn  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8000)
