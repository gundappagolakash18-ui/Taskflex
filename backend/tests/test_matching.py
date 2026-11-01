"""Matching engine: eligibility rules, component scores, weighted ranking."""

from datetime import datetime, timezone

from app.matching.config import get_matching_config
from app.matching.engine import MatchingEngine
from app.models import TaskAssignment
from app.schemas.task import TaskCreate
from app.services import TaskService

from tests.conftest import make_user, task_payload


def _make_task(db, customer, **overrides):
    service = TaskService(db)
    return service.create_task(customer, TaskCreate(**task_payload(**overrides)))


def test_eligibility_excludes_offline_unverified_and_far_workers(db):
    customer = make_user(db, "CUSTOMER")
    good = make_user(db, "WORKER", skills=("document_submission",))
    offline = make_user(db, "WORKER", skills=("document_submission",), is_online=False)
    unverified = make_user(db, "WORKER", skills=("document_submission",), is_verified=False)
    # ~17 km north of the task location, outside the default 8 km radius.
    far = make_user(
        db, "WORKER", skills=("document_submission",), latitude=16.0097, longitude=74.4977
    )

    task = _make_task(db, customer)
    engine = MatchingEngine(config=get_matching_config())
    eligible = engine.find_eligible_workers(db, task)

    eligible_ids = {w.user_id for w in eligible}
    assert eligible_ids == {good.id}
    assert offline.id not in eligible_ids
    assert unverified.id not in eligible_ids
    assert far.id not in eligible_ids


def test_capacity_exhausted_worker_is_not_eligible(db):
    customer = make_user(db, "CUSTOMER")
    busy = make_user(db, "WORKER", skills=("document_submission",))
    free = make_user(db, "WORKER", skills=("document_submission",))

    # busy is tied up on an ACTIVE assignment (max_concurrent_tasks defaults to 1).
    held_task = _make_task(db, customer)
    db.add(
        TaskAssignment(
            task_id=held_task.id,
            worker_id=busy.id,
            status="ACTIVE",
            accepted_at=datetime.now(timezone.utc),
            earnings_amount=100,
        )
    )
    db.commit()

    task = _make_task(db, customer)
    engine = MatchingEngine(config=get_matching_config())
    eligible_ids = {w.user_id for w in engine.find_eligible_workers(db, task)}
    assert busy.id not in eligible_ids
    assert free.id in eligible_ids


def test_ranking_prefers_the_closer_worker(db):
    customer = make_user(db, "CUSTOMER")
    near = make_user(db, "WORKER", skills=("document_submission",))  # same coords as task
    # ~3.3 km away — eligible, but a worse distance score.
    mid = make_user(db, "WORKER", skills=("document_submission",), latitude=15.8797)

    task = _make_task(db, customer)
    engine = MatchingEngine(config=get_matching_config())
    ranked = engine.rank_workers(db, task, engine.find_eligible_workers(db, task))

    assert [r.worker.user_id for r in ranked] == [near.id, mid.id]
    assert ranked[0].scores["skill_match"] == 1.0
    assert ranked[0].scores["availability"] == 1.0
    assert ranked[0].scores["distance_km"] < ranked[1].scores["distance_km"]
    assert ranked[0].final_score > ranked[1].final_score


def test_skill_match_rewards_matching_skills(db):
    customer = make_user(db, "CUSTOMER")
    skilled = make_user(db, "WORKER", skills=("document_submission",))
    unskilled = make_user(db, "WORKER", skills=("grocery_pickup",))

    task = _make_task(db, customer)
    engine = MatchingEngine(config=get_matching_config())
    ranked = engine.rank_workers(db, task, engine.find_eligible_workers(db, task))
    by_id = {r.worker.user_id: r for r in ranked}

    assert by_id[skilled.id].scores["skill_match"] == 1.0
    assert by_id[unskilled.id].scores["skill_match"] == 0.0
    assert ranked[0].worker.user_id == skilled.id


def test_final_score_is_the_weighted_sum():
    engine = MatchingEngine(config=get_matching_config())
    weights = get_matching_config().weights.as_dict()

    perfect = {name: 1.0 for name in weights}
    assert engine.calculate_final_score(perfect) == 1.0

    half_distance = dict.fromkeys(weights, 0.0)
    half_distance["distance"] = 0.5
    assert abs(engine.calculate_final_score(half_distance) - weights["distance"] * 0.5) < 1e-6
