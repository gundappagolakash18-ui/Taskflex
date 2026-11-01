from abc import ABC, abstractmethod
from datetime import datetime

from app.ai.schemas import ParsedTaskDraft


class AIProvider(ABC):
    """Abstraction over task-understanding backends.

    Implementations:
      * OpenAIProvider      — OpenAI chat models (requires OPENAI_API_KEY)
      * AnthropicProvider   — Anthropic Claude models (requires ANTHROPIC_API_KEY)
      * MockAIProvider      — offline deterministic NLU for development/demo

    The application selects a provider via the AI_PROVIDER environment variable
    and always falls back to the mock provider if the configured one fails.
    """

    name: str = "base"

    @abstractmethod
    def parse_task(self, text: str, now: datetime | None = None) -> ParsedTaskDraft:
        """Convert a natural-language request into a validated ParsedTaskDraft."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can currently serve requests (key present, etc.)."""
