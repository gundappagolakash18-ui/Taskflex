"""Mock AI provider — deterministic offline NLU used for development, tests and demos.

Implements a small rule-based extraction pipeline:
  1. keyword-scored task-type classification
  2. regex-based budget, date, time and location extraction
  3. missing-field detection that generates clarification questions
No network access and no API keys required.
"""

import re
from datetime import datetime, time, timedelta

from app.ai.providers.base import AIProvider
from app.ai.schemas import ParsedTaskDraft
from app.ai.task_classifier import TASK_TYPE_BY_SLUG, classify_text, skills_for_type
from app.core.logging import get_logger

logger = get_logger("ai.mock")

BUDGET_PATTERNS = [
    re.compile(r"(?:budget|pay|paid|payment|charge|cost|spend|spending|fee)\D{0,20}?₹?\s*([0-9][0-9,]{1,7})", re.I),
    re.compile(r"₹\s*([0-9][0-9,]{1,7})", re.I),
    re.compile(r"\brs\.?\s*([0-9][0-9,]{1,7})", re.I),
    re.compile(r"\b([0-9][0-9,]{1,7})\s*(?:rupees|rs\.?|inr|bucks)\b", re.I),
]

WEEKDAY_WORDS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

TIME_OF_DAY_SLOTS = {
    "morning": time(10, 0),
    "afternoon": time(14, 0),
    "evening": time(18, 0),
    "night": time(20, 0),
    "noon": time(12, 0),
}

LOCATION_PATTERNS = [
    re.compile(r"\bat (?:the |my |our )?(?P<loc>[a-z][a-z0-9 '\-\.,]{2,60}?)(?=\s*(?:,|\.|tomorrow|today|tonight|this|on |at \d|in the|by |and my budget|i can pay|budget|for me|$))", re.I),
    re.compile(r"\bfrom (?:the |my |our )?(?P<loc>[a-z][a-z0-9 '\-\.,]{2,60}?)(?=\s*(?:,|\.|to |tomorrow|today|tonight|this|and |by |$))", re.I),
    re.compile(r"\b(?:near|around|opposite|beside) (?:the )?(?P<loc>[a-z][a-z0-9 '\-]{2,60}?)(?=\s*(?:,|\.|tomorrow|today|$))", re.I),
]

STOP_LOCATIONS = {
    "you", "me", "us", "them", "it", "someone", "anyone", "person",
    "home", "house", "residence", "my place", "my home",
}

EXPLICIT_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)


class MockAIProvider(AIProvider):
    name = "mock"

    def parse_task(self, text: str, now: datetime | None = None) -> ParsedTaskDraft:
        now = now or datetime.now()
        raw = text.strip()
        lower = raw.lower()

        type_slug, type_confidence = classify_text(lower)
        meta = TASK_TYPE_BY_SLUG.get(type_slug)

        budget = self._extract_budget(lower)
        scheduled_date, date_confident = self._extract_date(lower, now)
        scheduled_time, time_of_day = self._extract_time(lower, now)
        location = self._extract_location(raw)
        urgency = self._extract_urgency(lower, scheduled_date, now)
        duration = meta.default_duration_minutes if meta else 60
        if "quick" in lower or "fast" in lower:
            duration = min(duration, 30)

        title = self._build_title(meta.label if meta else "Task", location)
        description = raw if len(raw) >= 10 else f"{raw} — {meta.description_hint if meta else 'miscellaneous errand'}"

        draft = ParsedTaskDraft(
            task_type=type_slug,  # type: ignore[arg-type]
            title=title,
            description=description,
            location=location,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            time_of_day=time_of_day,
            budget=budget,
            urgency=urgency,  # type: ignore[arg-type]
            required_skills=skills_for_type(type_slug),
            estimated_duration_minutes=duration,
            special_requirements=self._extract_special_requirements(lower),
            confidence=0.0,
            provider=self.name,
        )

        field_confidences = {
            "type": type_confidence,
            "location": 0.8 if location else 0.0,
            "datetime": 0.7 if (scheduled_date or time_of_day) else 0.0,
            "budget": 0.9 if budget else 0.0,
        }
        draft.confidence = round(
            0.30 * field_confidences["type"]
            + 0.25 * field_confidences["location"]
            + 0.20 * field_confidences["datetime"]
            + 0.15 * field_confidences["budget"]
            + (0.10 if len(raw) >= 40 else 0.05),
            2,
        )

        self._flag_missing(draft)
        return draft

    def is_available(self) -> bool:
        return True

    # ---------- extraction helpers ----------

    @staticmethod
    def _extract_budget(lower: str) -> float | None:
        for pattern in BUDGET_PATTERNS:
            match = pattern.search(lower)
            if match:
                raw = match.group(1).replace(",", "")
                try:
                    value = float(raw)
                except ValueError:
                    continue
                if 10 <= value <= 1_000_000:
                    return value
        return None

    @staticmethod
    def _extract_date(lower: str, now: datetime) -> tuple[object | None, bool]:
        if "day after tomorrow" in lower:
            return (now + timedelta(days=2)).date(), True
        if "tomorrow" in lower:
            return (now + timedelta(days=1)).date(), True
        if "today" in lower or "tonight" in lower or "asap" in lower or "right now" in lower or "immediately" in lower:
            return now.date(), True
        for word, weekday in WEEKDAY_WORDS.items():
            if word in lower:
                days_ahead = (weekday - now.weekday()) % 7
                days_ahead = days_ahead or 7  # "on monday" said on a monday means next monday
                return (now + timedelta(days=days_ahead)).date(), True
        if "this weekend" in lower:
            days_ahead = (5 - now.weekday()) % 7 or 7
            return (now + timedelta(days=days_ahead)).date(), True
        return None, False

    @staticmethod
    def _extract_time(lower: str, now: datetime) -> tuple[time | None, str | None]:
        explicit = EXPLICIT_TIME.search(lower)
        if explicit:
            hour = int(explicit.group(1)) % 12
            if explicit.group(3).lower() == "pm":
                hour += 12
            minute = int(explicit.group(2)) if explicit.group(2) else 0
            return time(hour, minute), None
        for word, slot in TIME_OF_DAY_SLOTS.items():
            if word in lower:
                return slot, word
        return None, None

    @staticmethod
    def _extract_location(raw: str) -> str | None:
        for pattern in LOCATION_PATTERNS:
            match = pattern.search(raw)
            if match:
                candidate = match.group("loc").strip(" .,")
                candidate_lower = candidate.lower()
                if candidate_lower in STOP_LOCATIONS or len(candidate) < 3:
                    continue
                # Trim dangling connectors left by the lookahead window.
                for connector in (" from", " to", " in", " at", " by", " on"):
                    if candidate_lower.endswith(connector):
                        candidate = candidate[: -len(connector)].strip(" .,")
                        break
                return candidate
        return None

    @staticmethod
    def _extract_urgency(lower: str, scheduled_date, now: datetime) -> str:
        if any(word in lower for word in ("urgent", "asap", "immediately", "right now", "emergency")):
            return "urgent"
        if any(word in lower for word in ("today", "tonight")):
            return "high"
        if scheduled_date is not None and (scheduled_date - now.date()).days <= 1:
            return "high"
        if any(word in lower for word in ("sometime", "next week", "whenever", "flexible", "no rush")):
            return "low"
        return "normal"

    @staticmethod
    def _extract_special_requirements(lower: str) -> list[str]:
        requirements = []
        if "female" in lower or "woman" in lower or "lady" in lower:
            requirements.append("female_worker_preferred")
        if "carry" in lower and ("print" in lower or "documents" in lower):
            requirements.append("carry_documents")
        if "id" in lower and ("bring" in lower or "carry" in lower):
            requirements.append("carry_id_card")
        return requirements

    @staticmethod
    def _build_title(label: str, location: str | None) -> str:
        if location:
            return f"{label} at {location}"
        return label

    @staticmethod
    def _flag_missing(draft: ParsedTaskDraft) -> None:
        from app.ai.clarification import attach_clarifications

        attach_clarifications(draft)
