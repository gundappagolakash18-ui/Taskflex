"""Shared missing-field detection + clarification question generation."""

from app.ai.schemas import ParsedTaskDraft

FIELD_QUESTIONS = {
    "location": "Where should the task be done? (address or landmark)",
    "scheduled_date": "When do you need this completed?",
    "budget": "What is your budget for this task?",
    "description": "Could you describe the task in a little more detail?",
}


def detect_missing_fields(draft: ParsedTaskDraft) -> list[str]:
    missing: list[str] = []
    if not draft.location or len(draft.location.strip()) < 3:
        missing.append("location")
    if draft.scheduled_date is None:
        missing.append("scheduled_date")
    if draft.budget is None:
        missing.append("budget")
    if len((draft.description or "").strip()) < 10:
        missing.append("description")
    return missing


def questions_for(missing: list[str]) -> list[str]:
    return [FIELD_QUESTIONS[field] for field in missing if field in FIELD_QUESTIONS]


def attach_clarifications(draft: ParsedTaskDraft) -> ParsedTaskDraft:
    draft.missing_fields = detect_missing_fields(draft)
    draft.clarification_questions = questions_for(draft.missing_fields)
    return draft
