"""OpenAI-backed task parser. The OpenAI SDK is imported lazily so the app runs
without it installed (the parser falls back to MockAIProvider)."""

from datetime import datetime

from app.ai.providers.base import AIProvider
from app.ai.providers.mock_provider import MockAIProvider
from app.ai.schemas import AIRawExtraction, ParsedTaskDraft, ProviderUnavailableError
from app.ai.task_classifier import TASK_TAXONOMY
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.openai")

SYSTEM_PROMPT = """You convert customer requests into structured real-world errand tasks.

Return ONLY a JSON object with these keys:
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
a field, use null / empty list. Dates must be absolute ISO dates resolved from
the current date given in the user message."""


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self) -> None:
        self._client = None

    def is_available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(settings.openai_api_key)

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderUnavailableError("openai package is not installed") from exc
        if not settings.openai_api_key:
            raise ProviderUnavailableError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(api_key=settings.openai_api_key)
        return self._client

    def parse_task(self, text: str, now: datetime | None = None) -> ParsedTaskDraft:
        now = now or datetime.now()
        client = self._get_client()
        types = ", ".join(t.slug for t in TASK_TAXONOMY) + ", other"
        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT.format(types=types)},
                    {
                        "role": "user",
                        "content": f"Current date: {now.date().isoformat()} (weekday {now.strftime('%A')}).\n"
                        f"Customer request: {text}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=700,
            )
            raw_json = response.choices[0].message.content or "{}"
        except Exception as exc:  # network, auth, rate limit -> caller falls back
            logger.warning("OpenAI parse failed: %s", exc)
            raise ProviderUnavailableError(f"OpenAI request failed: {exc}") from exc

        raw = AIRawExtraction.model_validate_json(raw_json)
        return self._to_draft(raw, text, now)

    def _to_draft(self, raw: AIRawExtraction, original_text: str, now: datetime) -> ParsedTaskDraft:
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


def get_openai_provider() -> AIProvider:
    """Factory that silently degrades to the mock provider when unavailable."""
    provider = OpenAIProvider()
    if provider.is_available():
        return provider
    logger.warning("OpenAI provider unavailable; using MockAIProvider")
    return MockAIProvider()
