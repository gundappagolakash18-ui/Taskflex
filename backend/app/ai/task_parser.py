"""TaskParser service: the single entry point the API uses to interpret
natural-language task requests. Guarantees a validated ParsedTaskDraft or a
clean 502 error — raw provider output never crosses this boundary."""

from datetime import datetime

from app.ai.clarification import attach_clarifications
from app.ai.providers import get_ai_provider
from app.ai.providers.base import AIProvider
from app.ai.providers.mock_provider import MockAIProvider
from app.ai.schemas import ParsedTaskDraft, ProviderUnavailableError
from app.core.exceptions import AIParseException
from app.core.logging import get_logger

logger = get_logger("ai.parser")


class TaskParser:
    def __init__(self, provider: AIProvider | None = None, fallback: AIProvider | None = None):
        self.provider = provider or get_ai_provider()
        self.fallback = fallback or MockAIProvider()

    def parse(self, text: str, now: datetime | None = None) -> ParsedTaskDraft:
        now = now or datetime.now()
        if not text or not text.strip():
            raise AIParseException("Please describe the task you need help with.")
        try:
            draft = self.provider.parse_task(text, now=now)
            draft = attach_clarifications(draft)
            logger.info(
                "task_parsed provider=%s type=%s confidence=%.2f missing=%s",
                draft.provider, draft.task_type, draft.confidence, draft.missing_fields,
            )
            return draft
        except (ProviderUnavailableError, AIParseException):
            if isinstance(self.provider, MockAIProvider):
                raise
        except Exception as exc:  # provider returned something unparseable
            logger.warning("AI provider '%s' produced invalid output: %s", self.provider.name, exc)

        logger.info("Falling back to MockAIProvider for task parsing")
        draft = self.fallback.parse_task(text, now=now)
        return attach_clarifications(draft)


_parser: TaskParser | None = None


def get_task_parser() -> TaskParser:
    global _parser
    if _parser is None:
        _parser = TaskParser()
    return _parser
