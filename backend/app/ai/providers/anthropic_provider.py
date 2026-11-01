"""Anthropic Claude-backed task parser. The anthropic SDK is imported lazily."""

import re
from datetime import datetime

from app.ai.providers.base import AIProvider
from app.ai.providers.mock_provider import MockAIProvider
from app.ai.schemas import AIRawExtraction, ParsedTaskDraft, ProviderUnavailableError
from app.ai.task_classifier import TASK_TAXONOMY
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.anthropic")

_SYSTEM_PROMPT = """You convert customer requests into structured real-world errand tasks.

Respond with ONLY a JSON object (no markdown fences, no prose) with keys:
- task_type: one of {types}
- title: short task title (max 80 chars)
- description: cleaned-up full description
- location: place/landmark mentioned (string or null)
- scheduled_date: ISO date resolved relative to the provided current date (or null)
- scheduled_time: "HH:MM" 24h time if stated (or null)
- time_of_day: morning|afternoon|evening|night (or null)
- budget: positive number in INR (or null)
- urgency: low|normal|high|urgent
- required_skills: list of short skill slugs like document_handling, queue_standing
- estimated_duration_minutes: integer 15..480
- special_requirements: list of short strings

Rules: never invent facts that are not in the request. If the user did not state
a field, use null / empty list."""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self) -> None:
        self._client = None

    def is_available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(settings.anthropic_api_key)

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderUnavailableError("anthropic package is not installed") from exc
        if not settings.anthropic_api_key:
            raise ProviderUnavailableError("ANTHROPIC_API_KEY is not configured")
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def parse_task(self, text: str, now: datetime | None = None) -> ParsedTaskDraft:
        now = now or datetime.now()
        client = self._get_client()
        types = ", ".join(t.slug for t in TASK_TAXONOMY) + ", other"
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=800,
                temperature=0.1,
                system=_SYSTEM_PROMPT.format(types=types),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Current date: {now.date().isoformat()} (weekday {now.strftime('%A')}).\n"
                            f"Customer request: {text}"
                        ),
                    }
                ],
            )
            raw_text = response.content[0].text if response.content else "{}"
        except Exception as exc:
            logger.warning("Anthropic parse failed: %s", exc)
            raise ProviderUnavailableError(f"Anthropic request failed: {exc}") from exc

        raw_json = self._extract_json(raw_text)
        raw = AIRawExtraction.model_validate_json(raw_json)
        return self._to_draft(raw, text)

    @staticmethod
    def _extract_json(text: str) -> str:
        fenced = _FENCE_RE.search(text)
        candidate = fenced.group(1) if fenced else text
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end != -1:
            return candidate[start : end + 1]
        return candidate

    def _to_draft(self, raw: AIRawExtraction, original_text: str) -> ParsedTaskDraft:
        from app.ai.clarification import attach_clarifications
        from app.models.enums import TaskType

        try:
            task_type = TaskType(raw.task_type)
        except ValueError:
            task_type = TaskType.OTHER

        scheduled_date = None
        if raw.scheduled_date:
            from datetime import date as date_cls

            scheduled_date = date_cls.fromisoformat(raw.scheduled_date)
        scheduled_time = None
        if raw.scheduled_time:
            from datetime import time as time_cls

            scheduled_time = time_cls.fromisoformat(raw.scheduled_time)

        draft = ParsedTaskDraft(
            task_type=task_type,
            title=raw.title or original_text[:80],
            description=raw.description or original_text,
            location=raw.location,
            latitude=raw.latitude,
            longitude=raw.longitude,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            time_of_day=raw.time_of_day,
            budget=raw.budget,
            urgency=raw.urgency,
            required_skills=raw.required_skills or [],
            estimated_duration_minutes=raw.estimated_duration_minutes,
            special_requirements=raw.special_requirements or [],
            confidence=0.9,
            provider=self.name,
        )
        return attach_clarifications(draft)


def get_anthropic_provider() -> AIProvider:
    provider = AnthropicProvider()
    if provider.is_available():
        return provider
    logger.warning("Anthropic provider unavailable; using MockAIProvider")
    return MockAIProvider()
