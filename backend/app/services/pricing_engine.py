"""Dynamic fare floor (Uber/Rapido-style pricing).

minimum_fare = (base + road_distance_km × per_km + wait_minutes × per_wait)
               × urgency multiplier

Road distance comes from OSRM (straight-line fallback when unreachable).
The recommended fare nudges above the floor to attract nearby workers.
Confirming a task whose budget sits below the floor is rejected with
BUDGET_BELOW_MINIMUM_FLOOR."""

from dataclasses import asdict, dataclass

from app.core.config import settings
from app.core.exceptions import BudgetBelowFloorException
from app.core.logging import get_logger
from app.models import Task
from app.tracking.routing import fetch_route

logger = get_logger("taskflex.pricing")

URGENCY_MULTIPLIERS = {
    "low": 1.0,
    "normal": 1.0,
    "high": 1.2,
    "urgent": 1.4,  # the directive's CRITICAL tier
}

BELOW_FLOOR_HINT = (
    "Tasks priced at the minimum fare take noticeably longer to fill — "
    "raising your budget closer to the recommended fare attracts workers faster."
)

ROUND_TRIP_RETURN_RATE = 0.5


@dataclass(frozen=True)
class FareQuote:
    currency: str
    base_fare: float
    distance_km: float
    distance_charge: float
    return_distance_km: float
    return_charge: float
    wait_minutes: float
    wait_charge: float
    subtotal: float
    urgency: str
    urgency_multiplier: float
    urgency_surcharge: float
    minimum_fare: float
    recommended_fare: float

    def to_dict(self) -> dict:
        return asdict(self)


def quote_from(
    *,
    distance_km: float,
    wait_minutes: float,
    urgency: str,
    return_distance_km: float = 0.0,
) -> FareQuote:
    urgency_key = (urgency or "normal").lower()
    multiplier = URGENCY_MULTIPLIERS.get(urgency_key, 1.0)

    base = settings.pricing_base_fare
    outbound_km = max(distance_km, 0.0)
    return_km = max(return_distance_km, 0.0)
    distance_charge = outbound_km * settings.pricing_per_km
    # A round trip pays the return leg at half the per-km rate.
    return_charge = return_km * settings.pricing_per_km * ROUND_TRIP_RETURN_RATE
    wait_charge = max(wait_minutes, 0.0) * settings.pricing_per_wait_minute
    subtotal = base + distance_charge + return_charge + wait_charge
    surcharge = subtotal * (multiplier - 1.0)
    minimum_fare = round(subtotal + surcharge, 2)
    recommended_fare = round(minimum_fare * settings.pricing_recommended_factor, 2)

    return FareQuote(
        currency="INR",
        base_fare=round(base, 2),
        distance_km=round(outbound_km, 2),
        distance_charge=round(distance_charge, 2),
        return_distance_km=round(return_km, 2),
        return_charge=round(return_charge, 2),
        wait_minutes=round(max(wait_minutes, 0.0), 1),
        wait_charge=round(wait_charge, 2),
        subtotal=round(subtotal, 2),
        urgency=urgency_key,
        urgency_multiplier=multiplier,
        urgency_surcharge=round(surcharge, 2),
        minimum_fare=minimum_fare,
        recommended_fare=recommended_fare,
    )


async def road_distance_km(
    origin: tuple[float, float], destination: tuple[float, float]
) -> float:
    route = await fetch_route(origin, destination)
    return float(route.distance_km)


def enforce_budget(task_price: float, quote: FareQuote, *, task_id: str | None = None) -> None:
    if float(task_price) >= quote.minimum_fare:
        return
    raise BudgetBelowFloorException(
        (
            f"Your budget ₹{float(task_price):.0f} is below the minimum fare "
            f"of ₹{quote.minimum_fare:.0f} for this task. {BELOW_FLOOR_HINT}"
        ),
        details={
            "your_budget": round(float(task_price), 2),
            "minimum_fare": quote.minimum_fare,
            "recommended_fare": quote.recommended_fare,
            "task_id": task_id,
        },
    )


def attached_locations(task: Task) -> dict[str, tuple[float, float]]:
    points: dict[str, tuple[float, float]] = {}
    for loc in task.locations or []:
        points[loc.label] = (float(loc.latitude), float(loc.longitude))
    return points


class PricingEngine:
    async def estimate(
        self,
        *,
        origin: tuple[float, float] | None,
        destination: tuple[float, float] | None,
        wait_minutes: float,
        urgency: str,
        is_round_trip: bool = False,
    ) -> FareQuote:
        distance_km = 0.0
        if origin is not None and destination is not None:
            same_spot = abs(origin[0] - destination[0]) < 1e-6 and abs(origin[1] - destination[1]) < 1e-6
            if not same_spot:
                distance_km = await road_distance_km(origin, destination)
        return quote_from(
            distance_km=distance_km,
            wait_minutes=wait_minutes,
            urgency=urgency,
            return_distance_km=distance_km if is_round_trip else 0.0,
        )

    async def floor_for_task(self, task: Task, *, wait_minutes: float = 0.0) -> FareQuote:
        """Floor for a saved task: when it carries both a pickup and a dropoff
        point the road distance between them prices the run; single-point tasks
        pay from the base fare. Round trips add the return leg at half rate."""
        points = attached_locations(task)
        origin = points.get("pickup")
        destination = points.get("dropoff") or points.get("primary")
        if origin is not None and destination is not None and origin != destination:
            return await self.estimate(
                origin=origin,
                destination=destination,
                wait_minutes=wait_minutes,
                urgency=task.urgency,
                is_round_trip=bool(task.is_round_trip),
            )
        return quote_from(
            distance_km=0.0,
            wait_minutes=wait_minutes,
            urgency=task.urgency,
            return_distance_km=0.0,
        )
