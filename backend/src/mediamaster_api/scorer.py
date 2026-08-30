"""Scorer Lambda: runs the taste engine outside the request path.

Invoked async by the API Lambda with:
    {"uid": "...", "mode": "full"}                  -> profile + score everything
    {"uid": "...", "mode": "single", "show_id": ""} -> score one show vs stored profile
"""

import logging
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from . import db, discover, seasons, series, taste
from .models import Medium, ShowCreate, ShowType, Status, now_iso

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

STALE_LOCK_MINUTES = 20


def handler(event, context):
    uid = event.get("uid")
    mode = event.get("mode", "full")
    medium = event.get("medium", "show")
    if uid is None:
        # Scheduled sweeps carry no uid: run for every registered user.
        results = {}
        for user in db.list_users():
            log.info("scheduled sweep for %s", user["email"])
            try:
                results[user["email"]] = _dispatch(user["uid"], mode, medium, event)
            except Exception:
                log.exception("sweep failed for %s; continuing", user["email"])
                results[user["email"]] = {"error": True}
        return results
    return _dispatch(uid, mode, medium, event)


def _dispatch(uid: str, mode: str, medium: str, event: dict):
    if mode == "single":
        return score_single(uid, event["show_id"])
    if mode == "discover":
        return run_discover(uid, medium)
    if mode == "scout":
        if medium == "all":  # monthly rule sweeps both boards
            return {"show": run_scout(uid),
                    "book": run_series_scout(uid)}
        if medium == "book":
            return run_series_scout(uid, series_name=event.get("series"))
        return run_scout(uid, franchise=event.get("franchise"))
    return run_full(uid, medium)


def is_running(profile: dict | None) -> bool:
    """True if a run is active and its lock isn't stale."""
    if not profile or profile.get("scoring_status") != "running":
        return False
    started = profile.get("started_at")
    if not started:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_LOCK_MINUTES)
    return datetime.fromisoformat(started) > cutoff


def run_full(uid: str, medium: str = "show") -> dict:
    profile_item = db.get_profile(uid, medium)
    if is_running(profile_item):
        log.info("run already in progress for %s/%s; skipping", uid, medium)
        return {"skipped": "already_running"}

    db.put_profile(uid, {"scoring_status": "running", "started_at": now_iso(),
                         "last_error": None}, medium)
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    try:
        shows = [s for s in db.list_shows(uid) if s.medium.value == medium]
        rated = [s for s in shows
                 if s.status == Status.poubelle or (s.status == Status.done and s.rating)]
        notes = (profile_item or {}).get("notes")

        log.info("stage A: generating %s profile from %d rated items", medium, len(rated))
        profile_text, usage = taste.generate_profile(taste.client(), rated, notes, medium)
        _add(totals, usage)
        version = taste.ratings_hash(shows)
        db.put_profile(uid, {
            "profile_text": profile_text,
            "generated_at": now_iso(),
            "ratings_hash": version,
        }, medium)

        queue = [s for s in shows if s.status == Status.to_watch]
        log.info("stage B: scoring %d shows in batches of %d", len(queue), taste.BATCH_SIZE)
        scored = 0
        for i in range(0, len(queue), taste.BATCH_SIZE):
            batch = queue[i:i + taste.BATCH_SIZE]
            scores, usage = taste.score_batch(taste.client(), profile_text, batch, medium)
            _add(totals, usage)
            log.info("batch %d: %d scores, usage=%s", i // taste.BATCH_SIZE + 1, len(scores), usage)
            ts = now_iso()
            for s in scores:
                try:
                    db.write_show_score(uid, s.show_id, s.score, s.reason, ts, version)
                    scored += 1
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        raise  # deleted mid-run: fine, skip

        est_cost = (totals["input_tokens"] * 5 + totals["output_tokens"] * 25
                    + totals["cache_read_input_tokens"] * 0.5
                    + totals["cache_creation_input_tokens"] * 6.25) / 1_000_000
        log.info("run complete: %d scored, usage=%s, est_cost=$%.2f", scored, totals, est_cost)
        db.put_profile(uid, {
            "scoring_status": "idle",
            "started_at": None,
            "last_run": {
                "finished_at": now_iso(),
                "scored": scored,
                "queue_size": len(queue),
                "usage": totals,
                "est_cost_usd": f"{est_cost:.2f}",
            },
        }, medium)
        return {"scored": scored}
    except Exception as e:
        log.exception("full run failed")
        db.put_profile(uid, {"scoring_status": "idle", "started_at": None,
                             "last_error": f"{type(e).__name__}: {e}"}, medium)
        raise


def score_single(uid: str, show_id: str) -> dict:
    show = db.get_show(uid, show_id)
    if show is None or show.status != Status.to_watch:
        return {"skipped": "not_scorable"}
    medium = show.medium.value
    profile_item = db.get_profile(uid, medium)
    profile_text = (profile_item or {}).get("profile_text")
    if not profile_text:
        log.info("no %s profile yet; skipping single-item scoring", medium)
        return {"skipped": "no_profile"}
    scores, usage = taste.score_batch(taste.client(), profile_text, [show], medium)
    log.info("single score for %s: usage=%s", show.name, usage)
    if scores:
        db.write_show_score(uid, show_id, scores[0].score, scores[0].reason,
                            now_iso(), profile_item.get("ratings_hash", ""))
    return {"scored": len(scores)}


def _add(totals: dict, usage: dict) -> None:
    for k in totals:
        totals[k] += usage.get(k, 0)




def scout_is_running(state: dict | None) -> bool:
    if not state or state.get("scout_status") != "running":
        return False
    started = state.get("started_at")
    if not started:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_LOCK_MINUTES)
    return datetime.fromisoformat(started) > cutoff


def run_scout(uid: str, franchise: str | None = None) -> dict:
    """Find released-but-untracked next seasons; create To Watch cards for them.

    franchise=None sweeps every eligible franchise (monthly / manual runs);
    a franchise name checks just that one (fired when Jon rates a season >=2).
    """
    full_sweep = franchise is None
    state = db.get_scout_state(uid)
    if full_sweep:
        if scout_is_running(state):
            log.info("scout already in progress for %s; skipping", uid)
            return {"skipped": "already_running"}
        db.put_scout_state(uid, {"scout_status": "running", "started_at": now_iso(),
                                 "last_error": None})

    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    try:
        shows = db.list_shows(uid)
        franchises = seasons.group_franchises(shows)
        if full_sweep:
            targets = [f for f in franchises.values() if seasons.eligible(f)]
        else:
            match = franchises.get(seasons._key(franchise))
            targets = [match] if match and seasons.eligible(match) else []
        log.info("scout: %d eligible franchises (%s)", len(targets),
                 "full sweep" if full_sweep else f"single: {franchise}")

        today = now_iso()[:10]
        created: list[str] = []
        checked = searched = 0
        for i in range(0, len(targets), seasons.SCOUT_BATCH_SIZE):
            batch = targets[i:i + seasons.SCOUT_BATCH_SIZE]
            candidates = [{"franchise": f.base, "have_season": f.max_season} for f in batch]
            results, usage, n_searches = seasons.check_franchises(
                taste.client(), candidates, today)
            _add(totals, usage)
            checked += len(candidates)
            searched += n_searches
            log.info("scout batch %d: %d results, %d searches, usage=%s",
                     i // seasons.SCOUT_BATCH_SIZE + 1, len(results), n_searches, usage)
            created.extend(_create_cards(uid, franchises, results))

        est_cost = (totals["input_tokens"] * 5 + totals["output_tokens"] * 25
                    + totals["cache_read_input_tokens"] * 0.5
                    + totals["cache_creation_input_tokens"] * 6.25) / 1_000_000
        log.info("scout complete: checked=%d searched=%d created=%s est_cost=$%.2f",
                 checked, searched, created, est_cost)
        run_info = {
            "finished_at": now_iso(),
            "mode": "full" if full_sweep else "single",
            "checked": checked,
            "web_searches": searched,
            "created": created,
            "est_cost_usd": f"{est_cost:.2f}",
        }
        if full_sweep:
            db.put_scout_state(uid, {"scout_status": "idle", "started_at": None,
                                     "last_run_show": run_info})
        else:
            # Single runs hold no lock — never touch scout_status/started_at,
            # or they release a concurrently running full sweep's lock.
            db.put_scout_state(uid, {"last_single_run_show": run_info})
        return {"created": created}
    except Exception as e:
        log.exception("scout run failed")
        if full_sweep:
            db.put_scout_state(uid, {"scout_status": "idle", "started_at": None,
                                     "last_error": f"{type(e).__name__}: {e}"})
        else:
            db.put_scout_state(uid, {"last_single_error_show": f"{type(e).__name__}: {e}"})
        raise


def _create_cards(uid: str, franchises: dict, results: list[dict]) -> list[str]:
    """Create To Watch cards for released next seasons; dedupe; taste-score."""
    profile_item = db.get_profile(uid)
    profile_text = (profile_item or {}).get("profile_text")
    created = []
    for r in results:
        if not r.get("released"):
            continue
        f = franchises.get(seasons._key(r.get("franchise", "")))
        if f is None:
            continue
        next_season = int(r.get("next_season") or f.max_season + 1)
        if f.max_season >= next_season:
            continue  # already on the board somewhere
        name = f"{f.base} Season {next_season}"
        show = db.create_show(uid, ShowCreate(
            name=name, show_type=ShowType.tv, service=f.service,
            source="Season Scout", status=Status.to_watch))
        note = (r.get("note") or "").strip()
        if profile_text:
            try:
                scores, usage = taste.score_batch(taste.client(), profile_text, [show])
                if scores:
                    db.write_show_score(
                        uid, show.show_id, scores[0].score,
                        f"{scores[0].reason} ({note})" if note else scores[0].reason,
                        now_iso(), (profile_item or {}).get("ratings_hash", ""))
            except Exception:
                log.exception("taste-scoring scout card %s failed; card kept", name)
        created.append(name)
    return created


def run_series_scout(uid: str, series_name: str | None = None) -> dict:
    """Find released-but-unowned next books in series; queue them in To Read.

    series_name=None sweeps every eligible series; a name checks just that one
    (fired when Jon rates a series book >=2).
    """
    full_sweep = series_name is None
    state = db.get_scout_state(uid)
    if full_sweep:
        if scout_is_running(state):
            log.info("series scout already in progress for %s; skipping", uid)
            return {"skipped": "already_running"}
        db.put_scout_state(uid, {"scout_status": "running", "started_at": now_iso(),
                                 "last_error": None})

    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    try:
        books = [s for s in db.list_shows(uid) if s.medium == Medium.book]
        groups = series.group_series(books)
        if full_sweep:
            targets = [g for g in groups.values() if series.eligible(g)]
        else:
            match = groups.get(series._key(series_name))
            targets = [match] if match and series.eligible(match) else []
        log.info("series scout: %d eligible series (%s)", len(targets),
                 "full sweep" if full_sweep else f"single: {series_name}")

        today = now_iso()[:10]
        created: list[str] = []
        checked = searched = 0
        for i in range(0, len(targets), series.SERIES_BATCH_SIZE):
            batch = targets[i:i + series.SERIES_BATCH_SIZE]
            candidates = [series.candidate_payload(g) for g in batch]
            results, usage, n_searches = series.check_series(
                taste.client(), candidates, today)
            _add(totals, usage)
            checked += len(candidates)
            searched += n_searches
            log.info("series scout batch %d: %d results, %d searches, usage=%s",
                     i // series.SERIES_BATCH_SIZE + 1, len(results), n_searches, usage)
            created.extend(_create_book_cards(uid, groups, results))

        est_cost = (totals["input_tokens"] * 5 + totals["output_tokens"] * 25
                    + totals["cache_read_input_tokens"] * 0.5
                    + totals["cache_creation_input_tokens"] * 6.25) / 1_000_000
        log.info("series scout complete: checked=%d searched=%d created=%s est_cost=$%.2f",
                 checked, searched, created, est_cost)
        run_info = {
            "finished_at": now_iso(),
            "mode": "full" if full_sweep else "single",
            "checked": checked,
            "web_searches": searched,
            "created": created,
            "est_cost_usd": f"{est_cost:.2f}",
        }
        if full_sweep:
            db.put_scout_state(uid, {"scout_status": "idle", "started_at": None,
                                     "last_run_book": run_info})
        else:
            db.put_scout_state(uid, {"last_single_run_book": run_info})
        return {"created": created}
    except Exception as e:
        log.exception("series scout run failed")
        if full_sweep:
            db.put_scout_state(uid, {"scout_status": "idle", "started_at": None,
                                     "last_error": f"{type(e).__name__}: {e}"})
        else:
            db.put_scout_state(uid, {"last_single_error_book": f"{type(e).__name__}: {e}"})
        raise


def run_discover(uid: str, medium: str) -> dict:
    """Find new titles matching the taste profile; pin them atop the queue."""
    state = db.get_scout_state(uid) or {}
    if state.get(f"discover_status_{medium}") == "running" and is_running(
        {"scoring_status": "running", "started_at": state.get(f"discover_started_at_{medium}")}
    ):
        log.info("%s discovery already in progress for %s; skipping", medium, uid)
        return {"skipped": "already running"}
    db.put_scout_state(uid, {f"discover_status_{medium}": "running",
                             f"discover_started_at_{medium}": now_iso()})
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    try:
        profile_item = db.get_profile(uid, medium)
        profile_text = (profile_item or {}).get("profile_text")
        if not profile_text:
            raise RuntimeError(
                f"No {medium} taste profile yet — rate a few and run a re-score first")

        shows = [s for s in db.list_shows(uid)
                 if (s.medium.value if hasattr(s.medium, "value") else s.medium) == medium]
        board_titles = sorted({s.name for s in shows})
        # franchise keys catch "recommend Breaking Bad" vs board's "Breaking Bad Season 2"
        taken_keys = {seasons._key(seasons.parse_name(s.name)[0]) for s in shows}
        taken_keys |= {seasons._key(s.series) for s in shows if s.series}

        candidates, usage, searches = discover.find_candidates(
            taste.client(), medium, profile_text, board_titles, now_iso()[:10])
        _add(totals, usage)

        now = now_iso()
        created: list[str] = []
        kept_per_category: dict[str, int] = {}
        for c in candidates:
            category = c.get("category") or ""
            name = (c.get("name") or "").strip()
            if not name or category not in ("movie", "tv", "book"):
                continue
            if (medium == "book") != (category == "book"):
                continue
            key = seasons._key(seasons.parse_name(name)[0])
            if key in taken_keys:
                continue
            if kept_per_category.get(category, 0) >= discover.PER_CATEGORY_KEPT:
                continue
            taken_keys.add(key)
            kept_per_category[category] = kept_per_category.get(category, 0) + 1

            series_name = (c.get("series") or "").strip() or None
            extra = (c.get("service_or_author") or "").strip() or None
            show = db.create_show(uid, ShowCreate(
                name=name,
                show_type=ShowType(category),
                medium=Medium(medium),
                service=extra if medium == "show" else None,
                author=extra if medium == "book" else None,
                series=series_name,
                series_index=(c.get("series_index") or None) if series_name else None,
                source="Discovery",
                status=Status.to_watch,
            ))
            db.write_show_score(
                uid, show.show_id,
                max(0, min(100, int(c.get("score") or 0))),
                (c.get("reason") or "").strip() or "profile fit",
                now, (profile_item or {}).get("ratings_hash", ""),
                discovered_at=now,
            )
            created.append(name)

        est_cost = (totals["input_tokens"] * 5 + totals["output_tokens"] * 25
                    + totals["cache_read_input_tokens"] * 0.5
                    + totals["cache_creation_input_tokens"] * 6.25) / 1_000_000
        log.info("discovery complete (%s): proposed=%d created=%s searches=%d est_cost=$%.2f",
                 medium, len(candidates), created, searches, est_cost)
        db.put_scout_state(uid, {
            f"discover_status_{medium}": "idle", f"discover_started_at_{medium}": None,
            f"last_discover_{medium}": {
                "finished_at": now_iso(), "created": created,
                "web_searches": searches, "est_cost_usd": f"{est_cost:.2f}",
            },
        })
        return {"created": created}
    except Exception as e:
        log.exception("discovery run failed")
        db.put_scout_state(uid, {f"discover_status_{medium}": "idle",
                                 f"discover_started_at_{medium}": None,
                                 f"last_discover_error_{medium}": f"{type(e).__name__}: {e}"})
        raise


def _create_book_cards(uid: str, groups: dict, results: list[dict]) -> list[str]:
    """Create To Read cards for released next-in-series books; dedupe; score."""
    profile_item = db.get_profile(uid, "book")
    profile_text = (profile_item or {}).get("profile_text")
    created = []
    for r in results:
        if not r.get("released") or not (r.get("next_title") or "").strip():
            continue
        g = groups.get(series._key(r.get("series", "")))
        if g is None:
            continue
        next_index = float(r.get("next_index") or 0) or None
        if next_index is not None and g.max_index >= next_index:
            continue  # already on the board somewhere
        title = r["next_title"].strip()
        if any(b.name.casefold() == title.casefold() for b in g.books):
            continue  # dedupe by exact title when the index is unhelpful
        show = db.create_show(uid, ShowCreate(
            name=title, show_type=ShowType.book, medium=Medium.book,
            author=(r.get("author") or g.author or None),
            series=g.name, series_index=next_index,
            source="Series Scout", status=Status.to_watch))
        note = (r.get("note") or "").strip()
        if profile_text:
            try:
                scores, usage = taste.score_batch(
                    taste.client(), profile_text, [show], "book")
                if scores:
                    db.write_show_score(
                        uid, show.show_id, scores[0].score,
                        f"{scores[0].reason} ({note})" if note else scores[0].reason,
                        now_iso(), (profile_item or {}).get("ratings_hash", ""))
            except Exception:
                log.exception("taste-scoring series card %s failed; card kept", title)
        created.append(title)
    return created
