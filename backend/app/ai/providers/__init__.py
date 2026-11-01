from app.ai.providers.base import AIProvider
from app.ai.providers.mock_provider import MockAIProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.factory")

_REGISTRY: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "mock": MockAIProvider,
}


def get_ai_provider() -> AIProvider:
    """Resolve the configured AI provider; degrade gracefully to the mock provider
    whenever the configured one is not usable (missing key, SDK, or unknown name)."""
    provider_cls = _REGISTRY.get(settings.ai_provider.lower())
    if provider_cls is None:
        logger.warning("Unknown AI_PROVIDER=%s; falling back to mock", settings.ai_provider)
        return MockAIProvider()
    provider = provider_cls()
    if not provider.is_available():
        logger.warning(
            "AI provider '%s' is not available (missing key or SDK); falling back to mock",
            provider.name,
        )
        return MockAIProvider()
    return provider


__all__ = ["AIProvider", "MockAIProvider", "OpenAIProvider", "AnthropicProvider", "get_ai_provider"]
