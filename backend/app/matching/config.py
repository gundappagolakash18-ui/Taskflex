from dataclasses import dataclass, field

from app.core.config import settings


@dataclass(frozen=True)
class MatchingWeights:
    """Weights for the multi-factor worker ranking score. All components are
    normalised to [0, 1] before weighting; the sum of weights must equal 1.0."""

    distance: float = 0.30
    skill_match: float = 0.25
    availability: float = 0.15
    rating: float = 0.15
    reliability: float = 0.10
    workload: float = 0.05

    def as_dict(self) -> dict[str, float]:
        return {
            "distance": self.distance,
            "skill_match": self.skill_match,
            "availability": self.availability,
            "rating": self.rating,
            "reliability": self.reliability,
            "workload": self.workload,
        }


DEFAULT_WEIGHTS = MatchingWeights()


@dataclass
class MatchingConfig:
    weights: MatchingWeights = field(default_factory=lambda: MatchingWeights(
        distance=_env_weight("distance", 0.30),
        skill_match=_env_weight("skill_match", 0.25),
        availability=_env_weight("availability", 0.15),
        rating=_env_weight("rating", 0.15),
        reliability=_env_weight("reliability", 0.10),
        workload=_env_weight("workload", 0.05),
    ))
    default_radius_km: float = settings.default_worker_radius_km
    rating_prior_weight: float = 3.0  # Bayesian prior: pretend 3 neutral ratings exist
    rating_prior_mean: float = 3.5
    reliability_prior_weight: float = 4.0
    reliability_prior_rate: float = 0.8
    no_skill_requirement_score: float = 0.7
    no_availability_info_score: float = 0.75
    unknown_location_score: float = 0.5


def _env_weight(name: str, default: float) -> float:
    import os

    raw = os.environ.get(f"MATCHING_WEIGHT_{name.upper()}")
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def get_matching_config() -> MatchingConfig:
    return MatchingConfig()
