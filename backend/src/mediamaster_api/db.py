import hashlib
import os
import secrets
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key
from ulid import ULID

from .models import Show, ShowCreate, ShowPatch, Status, now_iso
from .rank import rank_between

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def _user_pk(uid: str) -> str:
    return f"USER#{uid}"


def _show_sk(show_id: str) -> str:
    return f"SHOW#{show_id}"


def _item_to_show(item: dict) -> Show:
    return Show(
        show_id=item["show_id"],
        name=item["name"],
        show_type=item["show_type"],
        service=item.get("service"),
        source=item.get("source"),
        status=item["status"],
        rating=int(item["rating"]) if item.get("rating") is not None else None,
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        status_changed_at=item["status_changed_at"],
        rated_at=item.get("rated_at"),
        rank=item.get("rank"),
        medium=item.get("medium", "show"),
        author=item.get("author"),
        series=item.get("series"),
        series_index=float(item["series_index"]) if item.get("series_index") is not None else None,
        unverified=bool(item.get("unverified", False)),
        discovered_at=item.get("discovered_at"),
        llm_score=int(item["llm_score"]) if item.get("llm_score") is not None else None,
        llm_reason=item.get("llm_reason"),
        scored_at=item.get("scored_at"),
        profile_version=item.get("profile_version"),
    )


def list_shows(uid: str) -> list[Show]:
    shows: list[Show] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(_user_pk(uid)) & Key("SK").begins_with("SHOW#"),
        # Strongly consistent: scout dedupe reads its own just-written cards,
        # so back-to-back sweeps can't double-create. Costs 2x RCU — irrelevant here.
        "ConsistentRead": True,
    }
    while True:
        resp = table().query(**kwargs)
        shows.extend(_item_to_show(i) for i in resp["Items"])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return shows
        kwargs["ExclusiveStartKey"] = lek


def top_rank(uid: str, medium: str, status: str) -> str:
    """A rank above everything currently in the column."""
    current_top = None
    for s in list_shows(uid):
        if s.medium.value == medium and s.status.value == status and s.rank:
            if current_top is None or s.rank < current_top:
                current_top = s.rank
    return rank_between(None, current_top)


def create_show(uid: str, payload: ShowCreate) -> Show:
    now = now_iso()
    show_id = str(ULID())
    created_at = payload.created_at or now
    rating = payload.rating if payload.status == Status.done else None
    rank = payload.rank or top_rank(uid, payload.medium.value, payload.status.value)
    item = {
        "PK": _user_pk(uid),
        "SK": _show_sk(show_id),
        "show_id": show_id,
        "name": payload.name,
        "show_type": payload.show_type.value,
        "medium": payload.medium.value,
        "status": payload.status.value,
        "rank": rank,
        "created_at": created_at,
        "updated_at": now,
        "status_changed_at": now,
    }
    if payload.author:
        item["author"] = payload.author
    if payload.series:
        item["series"] = payload.series
    if payload.series_index is not None:
        item["series_index"] = Decimal(str(payload.series_index))
    if payload.unverified:
        item["unverified"] = True
    if payload.service:
        item["service"] = payload.service
    if payload.source:
        item["source"] = payload.source
    if rating is not None:
        item["rating"] = rating
        item["rated_at"] = now
    table().put_item(Item=item)
    return _item_to_show(item)


def get_show(uid: str, show_id: str) -> Optional[Show]:
    resp = table().get_item(Key={"PK": _user_pk(uid), "SK": _show_sk(show_id)})
    item = resp.get("Item")
    return _item_to_show(item) if item else None


def put_show(uid: str, show: Show) -> None:
    """Write a complete Show under a user's partition (transfer target path)."""
    item = show.model_dump(mode="json", exclude={"predicted_score", "score_breakdown"})
    ddb_item = {
        "PK": _user_pk(uid),
        "SK": _show_sk(show.show_id),
        **{k: v for k, v in item.items() if v is not None},
    }
    if ddb_item.get("series_index") is not None:  # DynamoDB rejects float
        ddb_item["series_index"] = Decimal(str(ddb_item["series_index"]))
    table().put_item(Item=ddb_item)


def patch_show(uid: str, show: Show, patch: ShowPatch, fields_set: set[str]) -> Show:
    now = now_iso()
    item = show.model_dump(mode="json", exclude={"predicted_score", "score_breakdown"})

    for field in ("name", "show_type", "service", "source", "rank",
                  "author", "series", "series_index", "unverified"):
        if field in fields_set:
            value = getattr(patch, field)
            item[field] = value.value if hasattr(value, "value") else value

    new_status = patch.status.value if "status" in fields_set and patch.status else item["status"]
    if new_status != item["status"]:
        item["status"] = new_status
        item["status_changed_at"] = now
        if "rank" not in fields_set:
            # Column change without a drop position: land on top. Lives here
            # (not just the route) so every caller gets collision-free ranks.
            item["rank"] = top_rank(uid, item["medium"], new_status)
        if new_status != Status.done.value:
            item["rating"] = None
            item["rated_at"] = None
    if "rating" in fields_set:
        item["rating"] = patch.rating
        item["rated_at"] = now if patch.rating is not None else None

    item["updated_at"] = now
    ddb_item = {
        "PK": _user_pk(uid),
        "SK": _show_sk(show.show_id),
        **{k: v for k, v in item.items() if v is not None},
    }
    if ddb_item.get("series_index") is not None:  # DynamoDB rejects float
        ddb_item["series_index"] = Decimal(str(ddb_item["series_index"]))
    table().put_item(Item=ddb_item)
    return _item_to_show(item)


def delete_show(uid: str, show_id: str) -> None:
    table().delete_item(Key={"PK": _user_pk(uid), "SK": _show_sk(show_id)})


def write_show_score(uid: str, show_id: str, score: int, reason: str,
                     scored_at: str, profile_version: str,
                     discovered_at: str | None = None) -> None:
    """Write LLM fields. Never touches rank or an existing discovery pin —
    ordering and pin-clearing belong to the user's Sort action, not scoring."""
    expr = "SET llm_score = :s, llm_reason = :r, scored_at = :t, profile_version = :v"
    values = {":s": score, ":r": reason, ":t": scored_at, ":v": profile_version}
    if discovered_at is not None:
        expr += ", discovered_at = :d"
        values[":d"] = discovered_at
    table().update_item(
        Key={"PK": _user_pk(uid), "SK": _show_sk(show_id)},
        # guard: the show may have been deleted mid-run
        ConditionExpression="attribute_exists(PK)",
        UpdateExpression=expr,
        ExpressionAttributeValues=values,
    )


def apply_sorted_ranks(uid: str, updates: list[tuple[str, str]]) -> None:
    """Sort action: write fresh ranks (and clear pins) for the given show_ids."""
    for show_id, new_rank in updates:
        table().update_item(
            Key={"PK": _user_pk(uid), "SK": _show_sk(show_id)},
            ConditionExpression="attribute_exists(PK)",
            UpdateExpression="SET #r = :r REMOVE discovered_at",
            ExpressionAttributeNames={"#r": "rank"},
            ExpressionAttributeValues={":r": new_rank},
        )


# --- Taste profile ------------------------------------------------------------

PROFILE_SK = "TASTE#PROFILE"


def _profile_sk(medium: str) -> str:
    # Shows keep the original SK so pre-books deployments' data stays live.
    return PROFILE_SK if medium == "show" else f"{PROFILE_SK}#{medium}"


def get_profile(uid: str, medium: str = "show") -> Optional[dict]:
    resp = table().get_item(Key={"PK": _user_pk(uid), "SK": _profile_sk(medium)})
    return resp.get("Item")


def put_profile(uid: str, updates: dict, medium: str = "show") -> None:
    """Merge updates into the medium's profile item (created on first write)."""
    existing = get_profile(uid, medium) or {"PK": _user_pk(uid), "SK": _profile_sk(medium)}
    existing.update(updates)
    table().put_item(Item={k: v for k, v in existing.items() if v is not None})


# --- Season scout state ---------------------------------------------------------

SCOUT_SK = "SCOUT#STATE"


def get_scout_state(uid: str) -> Optional[dict]:
    resp = table().get_item(Key={"PK": _user_pk(uid), "SK": SCOUT_SK})
    return resp.get("Item")


def put_scout_state(uid: str, updates: dict) -> None:
    """Merge updates into the scout-state item (created on first write)."""
    existing = get_scout_state(uid) or {"PK": _user_pk(uid), "SK": SCOUT_SK}
    existing.update(updates)
    table().put_item(Item={k: v for k, v in existing.items() if v is not None})


# --- Users registry -----------------------------------------------------------
# One row per account, so transfers can name a target and scheduled sweeps can
# loop everyone. Written by scripts/create_user.sh at account creation.

USERS_PK = "USERS"


def put_user(uid: str, email: str, display_name: str) -> None:
    table().put_item(Item={
        "PK": USERS_PK, "SK": f"USER#{uid}",
        "uid": uid, "email": email, "display_name": display_name,
    })


def list_users() -> list[dict]:
    resp = table().query(KeyConditionExpression=Key("PK").eq(USERS_PK))
    return [
        {"uid": i["uid"], "email": i["email"], "display_name": i.get("display_name", i["email"])}
        for i in resp["Items"]
    ]


def transfer_show(from_uid: str, to_uid: str, show: Show) -> Show:
    """Move a card to another user's board: fresh id, recipient re-scores."""
    moved = show.model_copy(update={
        "show_id": str(ULID()),
        "rank": top_rank(to_uid, show.medium.value, show.status.value),
        "llm_score": None, "llm_reason": None,
        "scored_at": None, "profile_version": None,
    })
    put_show(to_uid, moved)
    delete_show(from_uid, show.show_id)
    return moved


# --- API tokens ---------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(uid: str, label: str) -> dict:
    token = "mm_" + secrets.token_urlsafe(32)
    h = _token_hash(token)
    prefix = token[:11]  # "mm_" + 8 chars, enough to identify in a list
    now = now_iso()
    attrs = {"uid": uid, "label": label, "prefix": prefix, "created_at": now}
    table().put_item(Item={"PK": f"APITOKEN#{h}", "SK": "LOOKUP", **attrs})
    table().put_item(Item={"PK": _user_pk(uid), "SK": f"APITOKEN#{h}", **attrs})
    return {"token": token, "prefix": prefix, "label": label, "created_at": now}


def lookup_token(token: str) -> Optional[str]:
    """Return uid for a valid API token, else None."""
    if not token.startswith("mm_"):
        return None
    resp = table().get_item(Key={"PK": f"APITOKEN#{_token_hash(token)}", "SK": "LOOKUP"})
    item = resp.get("Item")
    return item["uid"] if item else None


def list_tokens(uid: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression=Key("PK").eq(_user_pk(uid)) & Key("SK").begins_with("APITOKEN#")
    )
    return [
        {"prefix": i["prefix"], "label": i["label"], "created_at": i["created_at"]}
        for i in resp["Items"]
    ]


def delete_token(uid: str, prefix: str) -> bool:
    resp = table().query(
        KeyConditionExpression=Key("PK").eq(_user_pk(uid)) & Key("SK").begins_with("APITOKEN#")
    )
    for item in resp["Items"]:
        if item["prefix"] == prefix:
            h_sk = item["SK"]  # APITOKEN#<hash>
            table().delete_item(Key={"PK": h_sk, "SK": "LOOKUP"})
            table().delete_item(Key={"PK": _user_pk(uid), "SK": h_sk})
            return True
    return False
