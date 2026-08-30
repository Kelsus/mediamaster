import random

import pytest

from mediamaster_api.rank import evenly_spaced, rank_between


def test_basic_midpoints():
    assert rank_between(None, None)  # any key
    mid = rank_between(None, None)
    assert rank_between(None, mid) < mid
    assert rank_between(mid, None) > mid


def test_between_is_strictly_ordered():
    a, b = "V", "W"
    m = rank_between(a, b)
    assert a < m < b


def test_adjacent_digits_go_deeper():
    m = rank_between("V", "W")
    assert m.startswith("V") and m > "V" and m < "W"
    m2 = rank_between("Vz", "W")
    assert "Vz" < m2 < "W"


def test_rejects_bad_order():
    with pytest.raises(ValueError):
        rank_between("b", "a")
    with pytest.raises(ValueError):
        rank_between("a", "a")


def test_evenly_spaced_sorted_and_gapped():
    keys = evenly_spaced(500)
    assert keys == sorted(keys)
    assert len(set(keys)) == 500
    # gaps admit midpoint insertion everywhere
    for a, b in zip(keys, keys[1:]):
        m = rank_between(a, b)
        assert a < m < b


def test_random_insertion_storm_keeps_total_order():
    rng = random.Random(42)
    keys = [rank_between(None, None)]
    for _ in range(2000):
        i = rng.randrange(len(keys) + 1)
        lo = keys[i - 1] if i > 0 else None
        hi = keys[i] if i < len(keys) else None
        keys.insert(i, rank_between(lo, hi))
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_prepend_storm_growth_is_bounded():
    k = rank_between(None, None)
    for _ in range(200):
        k = rank_between(None, k)
    assert len(k) < 60  # ~1 char per handful of prepends, not per prepend


def test_status_change_without_rank_gets_fresh_top_rank(client=None):
    """Regression: db-level status moves must re-rank, or emptied-and-refilled
    columns hand out colliding ranks (the all-'V' mock bug)."""
    import pytest
    pytest.importorskip("moto")
    from moto import mock_aws
    import boto3, os
    from mediamaster_api import db
    from mediamaster_api.models import ShowCreate, ShowPatch, Status

    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=os.environ["TABLE_NAME"],
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST")
        db._table = None
        ranks = []
        for name in ("A", "B", "C"):
            s = db.create_show("u1", ShowCreate(name=name, show_type="tv"))
            p = ShowPatch(status=Status.done)
            moved = db.patch_show("u1", s, p, p.model_fields_set)
            ranks.append(moved.rank)
        db._table = None
        assert len(set(ranks)) == 3, f"colliding ranks: {ranks}"
        # each later arrival lands on top (smaller rank)
        assert ranks == sorted(ranks, reverse=True)
