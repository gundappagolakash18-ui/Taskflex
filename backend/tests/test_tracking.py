"""Live tracking: geo math, OSRM routing, telemetry ingestion, snapshots,
and the end-to-end WebSocket flow (worker telemetry -> customer fan-out)."""

import asyncio

import pytest

from tests.conftest import auth_headers, make_user, task_payload

# ---------------------------------------------------------------- geo math --


def test_bearing_deg_cardinal_points():
    from app.tracking.geo import bearing_deg

    assert bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0)  # north
    assert bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0)  # east
    assert bearing_deg(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0)  # south
    assert bearing_deg(0.0, 0.0, 0.0, -1.0) == pytest.approx(270.0)  # west


def test_build_route_state_cumulative_distances():
    from app.tracking.geo import build_route_state

    coords = [(15.8497, 74.4977), (15.8497, 74.5030), (15.8497, 74.5100)]
    route = build_route_state(coords, 8.0)
    assert len(route.cumulative_km) == 3
    assert route.cumulative_km[0] == 0.0
    assert route.cumulative_km[2] == pytest.approx(route.distance_km, abs=1e-3)
    assert route.distance_km > 1.0  # ~1.3 km eastward
    assert route.destination == coords[-1]


def test_project_onto_route_midpoint_has_zero_deviation():
    from app.tracking.geo import build_route_state, project_onto_route

    coords = [(15.8497, 74.4977), (15.8497, 74.5100)]
    route = build_route_state(coords, 6.0)
    mid_lat = 15.8497
    mid_lng = (74.4977 + 74.5100) / 2
    projection = project_onto_route(route, mid_lat, mid_lng)
    assert projection.deviation_km < 0.001
    assert projection.along_km == pytest.approx(route.distance_km / 2, rel=0.02)
    assert projection.segment_index == 0


def test_project_onto_route_measures_off_route_deviation():
    from app.tracking.geo import build_route_state, project_onto_route

    coords = [(15.8497, 74.4977), (15.8497, 74.5100)]
    route = build_route_state(coords, 6.0)
    # 0.01 deg north of the straight east-west line is roughly 1.11 km off.
    projection = project_onto_route(route, 15.8597, 74.5038)
    assert projection.deviation_km == pytest.approx(1.11, abs=0.05)


def test_eta_minutes_live_speed_and_prorated_fallback():
    from app.tracking.geo import RouteState, build_route_state, eta_minutes

    route = build_route_state([(0.0, 0.0), (0.0, 0.02)], 10.0)
    # Live speed: 2 km remaining at 24 km/h -> 5 minutes.
    assert eta_minutes(2.0, 24.0, 10.0, route, 0.0) == pytest.approx(5.0)
    # Slow/no speed: pro-rate planned duration by remaining fraction.
    assert eta_minutes(route.distance_km, 0.0, 10.0, route, 0.0) == pytest.approx(10.0)
    assert eta_minutes(route.distance_km / 2, 0.0, 10.0, route, 0.0) == pytest.approx(5.0)


# ----------------------------------------------------------------- routing --


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeAsyncClient:
    payload: dict = {}

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _FakeResponse(self.payload)


def test_fetch_route_parses_osrm_geojson(monkeypatch):
    from app.tracking import routing

    _FakeAsyncClient.payload = {
        "routes": [
            {
                "duration": 600.0,
                "geometry": {
                    "coordinates": [
                        [74.4977, 15.8497],
                        [74.5050, 15.8550],
                        [74.5100, 15.8600],
                    ]
                },
            }
        ]
    }
    monkeypatch.setattr(routing.httpx, "AsyncClient", _FakeAsyncClient)
    routing.clear_route_cache()

    route = asyncio.run(routing.fetch_route((15.8497, 74.4977), (15.8600, 74.5100)))
    # GeoJSON [lng, lat] must be converted to (lat, lng) tuples.
    assert route.coordinates[0] == (15.8497, 74.4977)
    assert route.coordinates[-1] == (15.8600, 74.5100)
    assert route.duration_min == pytest.approx(10.0)
    assert len(route.coordinates) == 3


def test_fetch_route_falls_back_to_straight_line(monkeypatch):
    from app.core.config import settings
    from app.tracking import routing
    from app.matching.geo import haversine_km

    monkeypatch.setattr(settings, "osrm_base_url", "http://127.0.0.1:9")
    routing.clear_route_cache()

    origin, destination = (15.8497, 74.4977), (15.8600, 74.5100)
    route = asyncio.run(routing.fetch_route(origin, destination))
    assert len(route.coordinates) == 2
    assert route.distance_km == pytest.approx(haversine_km(*origin, *destination), abs=1e-3)
    # Straight-line fallback assumes a conservative 22 km/h city average.
    assert route.duration_min == pytest.approx(route.distance_km / 22.0 * 60.0, rel=0.01)


# ----------------------------------------------------------- map matching --


def test_snap_point_uses_osrm_nearest(monkeypatch):
    from app.core.config import settings
    from app.tracking import routing

    _FakeAsyncClient.payload = {
        "waypoints": [{"location": [74.4980, 15.8500], "distance": 12.4}]
    }
    monkeypatch.setattr(routing.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "tracking_map_match_enabled", True)
    routing.clear_route_cache()

    snapped = asyncio.run(routing.snap_point((15.8497, 74.4977)))
    # GeoJSON [lng, lat] -> (lat, lng)
    assert snapped == pytest.approx((15.8500, 74.4980))


def test_snap_point_rejects_a_fix_farther_than_the_radius(monkeypatch):
    from app.core.config import settings
    from app.tracking import routing

    _FakeAsyncClient.payload = {
        "waypoints": [{"location": [74.4980, 15.8500], "distance": 800.0}]
    }
    monkeypatch.setattr(routing.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "tracking_map_match_enabled", True)
    routing.clear_route_cache()

    assert asyncio.run(routing.snap_point((15.8497, 74.4977), radius_m=50)) is None


def test_snap_point_degrades_to_none_when_osrm_is_down(monkeypatch):
    from app.core.config import settings
    from app.tracking import routing

    monkeypatch.setattr(settings, "osrm_base_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "tracking_map_match_enabled", True)
    routing.clear_route_cache()

    assert asyncio.run(routing.snap_point((15.8497, 74.4977))) is None


def test_snap_trace_returns_one_matched_point_per_fix(monkeypatch):
    from app.core.config import settings
    from app.tracking import routing

    _FakeAsyncClient.payload = {
        "tracepoints": [
            {"location": [74.4978, 15.8498]},
            None,
        ]
    }
    monkeypatch.setattr(routing.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "tracking_map_match_enabled", True)
    routing.clear_route_cache()

    matched = asyncio.run(
        routing.snap_trace([(15.8497, 74.4977), (15.8497, 74.5100)])
    )
    assert matched == [pytest.approx((15.8498, 74.4978)), None]


def test_ingest_broadcasts_the_snapped_fix(db, fake_route, monkeypatch):
    from app.tracking import service

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER", skills=("document_submission",))
    task = _make_accepted_task(db, customer, worker)

    async def _fake_snap(point):
        return (15.8501, 74.4981)

    monkeypatch.setattr("app.tracking.service.snap_point", _fake_snap)

    payload = asyncio.run(
        service.ingest_worker_position(db, worker, task.id, 15.8497, 74.4977, speed_kmph=18.0)
    )
    assert payload["latitude"] == pytest.approx(15.8501)
    assert payload["longitude"] == pytest.approx(74.4981)
    assert payload["snapped"] is True


# ------------------------------------------------------------ ingest / hub --


@pytest.fixture(autouse=True)
def _clean_tracking_state():
    from app.tracking import hub, service

    def _wipe():
        service._last_ping.clear()
        service._routes.clear()
        hub._latest_local.clear()
        hub._history_local.clear()
        hub._subs.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture()
def fake_route(monkeypatch):
    coords = [(15.8497, 74.4977), (15.8497, 74.5100)]

    async def _fake(origin, destination):
        from app.tracking.geo import build_route_state

        return build_route_state(list(coords), 8.0)

    monkeypatch.setattr("app.tracking.service.fetch_route", _fake)
    return coords


def _make_accepted_task(db, customer, worker, status="ACCEPTED"):
    from app.models import Task
    from app.models.enums import TaskStatus

    payload = task_payload()
    task = Task(
        customer_id=customer.id,
        title=payload["title"],
        description=payload["description"],
        task_type=payload["task_type"],
        status=status if isinstance(status, str) else TaskStatus(status).value,
        urgency=payload["urgency"],
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        address_text=payload["address_text"],
        area_name=payload["area_name"],
        city=payload["city"],
        budget=payload["budget"],
        assigned_worker_id=worker.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_ingest_publishes_payload_and_caches_latest(db, fake_route):
    from app.tracking import hub, service

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    payload = asyncio.run(
        service.ingest_worker_position(db, worker, task.id, 15.8497, 74.5038, heading=None, speed_kmph=24.0)
    )
    assert payload is not None
    assert payload["task_id"] == task.id
    assert payload["status"] == "ACCEPTED"
    assert payload["latitude"] == pytest.approx(15.8497)
    assert payload["heading"] == pytest.approx(90.0, abs=1.0)  # derived: heading east
    assert 0 < payload["remaining_km"] < 1.5
    assert payload["eta_minutes"] > 0

    cached = asyncio.run(hub.latest(task.id))
    assert cached == payload


def test_ingest_rejects_unassigned_worker_and_wrong_state(db, fake_route):
    from app.tracking import service

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    stranger = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    assert asyncio.run(service.ingest_worker_position(db, stranger, task.id, 15.8497, 74.5)) is None

    pending_task = _make_accepted_task(db, customer, worker, status="PENDING_CONFIRMATION")
    assert asyncio.run(service.ingest_worker_position(db, worker, pending_task.id, 15.8497, 74.5)) is None

    assert asyncio.run(service.ingest_worker_position(db, worker, "nonexistent-task", 15.8497, 74.5)) is None


def test_ingest_throttles_burst_pings(db, fake_route):
    from app.tracking import service

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    first = asyncio.run(service.ingest_worker_position(db, worker, task.id, 15.8497, 74.50))
    second = asyncio.run(service.ingest_worker_position(db, worker, task.id, 15.8497, 74.51))
    assert first is not None
    assert second is None  # inside the 3 s minimum interval


# ---------------------------------------------------------------- REST API --


def test_tracking_snapshot_rest(db, client, fake_route):
    from app.tracking import hub, service

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    payload = asyncio.run(service.ingest_worker_position(db, worker, task.id, 15.8497, 74.5038))
    assert payload is not None

    resp = client.get(f"/api/v1/tasks/{task.id}/tracking", headers=auth_headers(customer))
    assert resp.status_code == 200
    body = resp.json()["data"]["tracking"]
    assert body["destination"] == {"latitude": 15.8497, "longitude": 74.4977}
    assert body["latest"]["latitude"] == pytest.approx(15.8497)
    assert body["worker"]["full_name"] == worker.full_name
    assert body["worker"].get("phone") is None  # never leak contact details
    assert body["route"] is not None
    assert len(body["route"]["coordinates"]) == 2

    # Stranger must not watch someone else's task.
    outsider = make_user(db, "CUSTOMER")
    resp = client.get(f"/api/v1/tasks/{task.id}/tracking", headers=auth_headers(outsider))
    assert resp.status_code == 403


def test_tracking_snapshot_rest_before_first_ping(db, client):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    resp = client.get(f"/api/v1/tasks/{task.id}/tracking", headers=auth_headers(customer))
    assert resp.status_code == 200
    body = resp.json()["data"]["tracking"]
    assert body["latest"] is None
    assert body["worker"]["full_name"] == worker.full_name


# ------------------------------------------------------------ WebSocket E2E --


def test_websocket_worker_telemetry_round_trip(db, client, fake_route):
    """One socket, full path: auth -> subscribe -> ingest -> publish -> deliver.

    (TestClient runs each websocket in its own portal, so a message the server
    pushes to a *different* socket cannot wake that socket's blocked receive;
    the assigned worker watching their own task exercises the same code path.)"""
    from app.tracking import hub

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    worker_token = auth_headers(worker)["Authorization"].split()[-1]

    with client.websocket_connect(f"/ws?token={worker_token}") as ws:
        ws.send_json({"event": "subscribe_tracking", "data": {"task_id": task.id}})
        # Round-trip: once the pong arrives, the subscribe above is definitely processed.
        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"
        assert hub._subs.get(task.id) == {worker.id}

        ws.send_json(
            {
                "event": "location_update",
                "data": {"task_id": task.id, "latitude": 15.8497, "longitude": 74.5038, "speed_kmph": 24.0},
            }
        )
        event = ws.receive_json()
        assert event["event"] == "tracking_update"
        assert event["data"]["task_id"] == task.id
        assert event["data"]["latitude"] == pytest.approx(15.8497)
        assert event["data"]["eta_minutes"] > 0


def test_hub_publishes_only_to_subscribers(db, monkeypatch):
    from app.tracking import hub
    from app.websocket import manager as manager_module

    delivered: list[tuple[list[str], str, dict]] = []

    async def _record(user_ids, event, data):
        delivered.append((list(user_ids), event, data))
        return len(user_ids)

    monkeypatch.setattr(manager_module.manager, "send_to_users", _record)

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_accepted_task(db, customer, worker)

    hub.subscribe(task.id, customer.id)
    asyncio.run(hub.publish(task.id, {"task_id": task.id, "latitude": 15.85}))
    assert delivered == [([customer.id], "tracking_update", {"task_id": task.id, "latitude": 15.85})]

    # Unsubscribed watchers must not receive anything, and latest stays cached.
    delivered.clear()
    hub.unsubscribe(task.id, customer.id)
    asyncio.run(hub.publish(task.id, {"task_id": task.id, "latitude": 15.86}))
    assert delivered == []
    assert asyncio.run(hub.latest(task.id))["latitude"] == 15.86


def test_websocket_unrelated_user_cannot_subscribe(db, client):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    stranger = make_user(db, "CUSTOMER")
    task = _make_accepted_task(db, customer, worker)

    stranger_token = auth_headers(stranger)["Authorization"].split()[-1]
    with client.websocket_connect(f"/ws?token={stranger_token}") as sws:
        sws.send_json({"event": "subscribe_tracking", "data": {"task_id": task.id}})
        sws.send_text("ping")
        assert sws.receive_json()["event"] == "pong"
        assert hub_subscribed(task.id, stranger.id) is False


def hub_subscribed(task_id: str, user_id: str) -> bool:
    from app.tracking import hub

    return user_id in hub._subs.get(task_id, set())
