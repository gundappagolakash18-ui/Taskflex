"""Task-type taxonomy shared by the AI providers and the mock NLU engine."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskTypeMeta:
    slug: str
    label: str
    keywords: tuple[str, ...]
    skills: tuple[str, ...] = ()
    default_duration_minutes: int = 60
    description_hint: str = ""


TASK_TAXONOMY: tuple[TaskTypeMeta, ...] = (
    TaskTypeMeta(
        slug="document_submission",
        label="Document Submission",
        keywords=("submit", "submission", "hand in", "handover", "deposit", "give documents",
                  "submit documents", "file submission", "attest", "notary"),
        skills=("document_handling", "government_office"),
        default_duration_minutes=60,
        description_hint="Submitting documents at an office on the customer's behalf.",
    ),
    TaskTypeMeta(
        slug="queue_standing",
        label="Queue Standing",
        keywords=("stand in line", "standing in queue", "queue", "wait in line", "token",
                  "stand in the line", "hold my place", "serpentine"),
        skills=("queue_standing", "patience"),
        default_duration_minutes=90,
        description_hint="Standing in a queue to hold the customer's place.",
    ),
    TaskTypeMeta(
        slug="government_office",
        label="Government Office Assistance",
        keywords=("government office", "municipal", "corporation office", "taluk", "tehsil",
                  "panchayat", "rto", "registrar", "sarkari", "civic office", "bbmp", "mro"),
        skills=("government_office", "document_handling"),
        default_duration_minutes=90,
        description_hint="Assistance with work at a government office.",
    ),
    TaskTypeMeta(
        slug="document_collection",
        label="Document Collection",
        keywords=("collect", "collection", "pick up my documents", "fetch", "retrieve",
                  "get my documents", "obtain", "certificate collect", "medical report",
                  "lab report", "reports collect", "diagnostic"),
        skills=("document_handling", "timely_delivery"),
        default_duration_minutes=60,
        description_hint="Collecting documents from a location.",
    ),
    TaskTypeMeta(
        slug="courier_pickup",
        label="Courier / Document Pickup",
        keywords=("courier", "bluedart", "dhl", "fedex", "deliver", "delivery", "dispatch",
                  "speed post", "drop off", "send documents"),
        skills=("courier_handling", "timely_delivery"),
        default_duration_minutes=60,
        description_hint="Courier or document pickup and drop-off.",
    ),
    TaskTypeMeta(
        slug="form_submission",
        label="Form Submission",
        keywords=("form", "application", "apply on my behalf", "fill form", "entrance form",
                  "exam form", "scholarship form"),
        skills=("document_handling", "form_filling"),
        default_duration_minutes=45,
        description_hint="Filling and submitting a form on the customer's behalf.",
    ),
    TaskTypeMeta(
        slug="appointment_assistance",
        label="Appointment Assistance",
        keywords=("appointment", "book a slot", "schedule", "reservation", "registration desk",
                  "hospital registration", "opd", "token booking", "register", "hospital",
                  "clinic", "dispensary"),
        skills=("communication", "hospital_navigation"),
        default_duration_minutes=60,
        description_hint="Helping secure or manage an appointment.",
    ),
    TaskTypeMeta(
        slug="grocery_pickup",
        label="Grocery / Item Pickup",
        keywords=("grocery", "groceries", "vegetables", "medicines", "medicine pickup", "pharmacy",
                  "buy and bring", "purchase", "provisions", "milk", "supermarket"),
        skills=("shopping", "timely_delivery"),
        default_duration_minutes=45,
        description_hint="Buying or picking up items and bringing them to the customer.",
    ),
    TaskTypeMeta(
        slug="parcel_collection",
        label="Parcel Collection",
        keywords=("parcel", "package", "shipment", "railway station parcel", "collect parcel",
                  "collect package", "pick up my parcel", "pick up the parcel", "collect my parcel",
                  "warehouse pickup", "hub pickup"),
        skills=("courier_handling", "timely_delivery"),
        default_duration_minutes=45,
        description_hint="Collecting a parcel from a station, hub or shop.",
    ),
    TaskTypeMeta(
        slug="office_errand",
        label="Office Errand",
        keywords=("office errand", "my office", "head office", "branch office", "corporate",
                  "sign documents at office", "office work"),
        skills=("office_errand", "document_handling"),
        default_duration_minutes=60,
        description_hint="An errand at a company office.",
    ),
    TaskTypeMeta(
        slug="bank_assistance",
        label="Bank Assistance (non-financial)",
        keywords=("bank", "passbook", "cheque book", "kyc", "branch", "atm", "demand draft",
                  "bank statement"),
        skills=("bank_procedures", "document_handling"),
        default_duration_minutes=60,
        description_hint="Non-financial assistance at a bank branch.",
    ),
    TaskTypeMeta(
        slug="college_work",
        label="College / University Work",
        keywords=("college", "university", "campus", "department office", "hall ticket",
                  "transcript", "bonafide", "degree certificate", "registrar college"),
        skills=("document_handling", "campus_navigation"),
        default_duration_minutes=60,
        description_hint="Running an errand at a college or university.",
    ),
    TaskTypeMeta(
        slug="local_errand",
        label="Local Errand",
        keywords=("errand", "pick up", "drop", "bring", "local work", "small work", "help me with"),
        skills=("local_travel",),
        default_duration_minutes=45,
        description_hint="A miscellaneous local errand.",
    ),
)

TASK_TYPE_BY_SLUG = {t.slug: t for t in TASK_TAXONOMY}


def classify_text(text: str) -> tuple[str, float]:
    """Return (task_type_slug, confidence) for free text using keyword scoring."""
    normalized = " " + " ".join(text.lower().split()) + " "
    scores: dict[str, float] = {}
    for meta in TASK_TAXONOMY:
        score = 0.0
        for keyword in meta.keywords:
            if keyword in normalized:
                # Longer, more specific keywords weigh more.
                score += min(len(keyword.split()), 3) * 1.0
        if score:
            scores[meta.slug] = score
    if not scores:
        return "other", 0.3
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    total = sum(scores.values())
    return best, min(0.95, 0.5 + 0.45 * (scores[best] / total))


def skills_for_type(slug: str) -> list[str]:
    meta = TASK_TYPE_BY_SLUG.get(slug)
    return list(meta.skills) if meta else []


def label_for_type(slug: str) -> str:
    meta = TASK_TYPE_BY_SLUG.get(slug)
    return meta.label if meta else "Other Task"
