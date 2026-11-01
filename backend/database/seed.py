"""Deterministic demo dataset for TASKFLEX.

Creates 1 admin, 10 customers, 20 workers, 10 skills and 30 tasks spanning the
full task lifecycle (DRAFT -> CANCELLED/DISPUTED), plus payments, wallets,
ratings, reviews, conversations, notifications, verification documents, audit
logs and system settings. Everything is centred on Belagavi, Karnataka.

All demo accounts share the password ``Demo@1234``; the admin account uses its
own credentials (``ADMIN_NAME`` / ``ADMIN_PASSWORD``).

Run standalone from backend/::

    python -m database.seed
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import hash_password
from app.models import (
    AuditLog,
    Conversation,
    CustomerProfile,
    Dispute,
    Message,
    Notification,
    Payment,
    Rating,
    RatingDirection,
    Review,
    SavedLocation,
    Skill,
    SystemSetting,
    Task,
    TaskAssignment,
    TaskLocation,
    TaskOffer,
    TaskRequirement,
    TaskStatus,
    TaskStatusHistory,
    Transaction,
    TransactionType,
    User,
    UserRole,
    VerificationDocument,
    VerificationStatus,
    Wallet,
    WorkerAvailability,
    WorkerProfile,
    WorkerSkill,
)

logger = get_logger("db.seed")

DEMO_PASSWORD = "Demo@1234"
ADMIN_EMAIL = "admin@taskflex.dev"
ADMIN_NAME = "akash g"
ADMIN_PASSWORD = "akash@#123"
CITY = "Belagavi"
CENTER_LAT = 15.8497
CENTER_LNG = 74.4977
COMMISSION_PERCENT = 10.0

rng = random.Random(42)

SKILLS: list[tuple[str, str, str, str]] = [
    ("Document Submission", "document_submission", "paperwork", "Drop off applications, forms and certificates at offices."),
    ("Queue Standing", "queue_standing", "assistance", "Hold your place in long queues at offices and hospitals."),
    ("Government Office Work", "government_office", "paperwork", "RTO, municipal and tahsildar office errands."),
    ("Document Collection", "document_collection", "paperwork", "Collect certificates, approvals and printouts."),
    ("Courier & Parcel Pickup", "courier_pickup", "delivery", "Pick up parcels from courier hubs and bring them to you."),
    ("Grocery Pickup", "grocery_pickup", "shopping", "Pick up groceries and medicines from local shops."),
    ("Bank Assistance", "bank_assistance", "finance", "Non-financial bank errands like passbook updates and challans."),
    ("Hospital Assistance", "hospital_assistance", "healthcare", "OPD registration, tokens and patient assistance."),
    ("Form Filling", "form_filling", "paperwork", "Online and offline application form filling."),
    ("Local Errands", "local_errand", "general", "Any short errand within the city."),
]

CUSTOMERS: list[str] = [
    "Ananya Deshpande",
    "Rohit Kulkarni",
    "Sneha Patil",
    "Vikram Shetty",
    "Meera Joshi",
    "Arjun Naik",
    "Priya Hegde",
    "Karthik Rao",
    "Divya Kamat",
    "Sahil Pawar",
]

# (name, skill indexes, experience years, languages)
WORKERS: list[tuple[str, list[int], int, str]] = [
    ("Ravi Chavan", [0, 1, 2], 6, "Kannada, Hindi, English"),
    ("Suresh Bhat", [2, 3, 8], 4, "Kannada, English"),
    ("Ganesh Joshi", [1, 7], 8, "Kannada, Hindi, Marathi"),
    ("Prakash Gowda", [4, 9], 3, "Kannada, Hindi"),
    ("Mahesh Desai", [5, 9], 2, "Kannada, English"),
    ("Nitin Kulkarni", [0, 3, 8], 5, "Kannada, Marathi, English"),
    ("Vinayak Hegde", [6], 7, "Kannada, English"),
    ("Sadanand Pai", [1, 2, 7], 9, "Kannada, Hindi"),
    ("Ramesh Kudtarkar", [4, 5], 4, "Kannada, Hindi, English"),
    ("Ibrahim Shaikh", [0, 2], 3, "Urdu, Kannada, Hindi"),
    ("Deepak Nayak", [5, 6, 9], 1, "Kannada, English"),
    ("Chetan Ambekar", [8, 0, 3], 6, "Marathi, Kannada"),
    ("Basavaraj Hiremath", [2, 1], 10, "Kannada, Hindi"),
    ("Sridhar Bhandari", [7, 1], 5, "Kannada, Tulu"),
    ("Manjunath Solanki", [9, 4], 2, "Kannada, Hindi"),
    ("Faisal Khan", [4, 0, 5], 4, "Hindi, Urdu, English"),
    ("Girish Nadkarni", [6, 8], 8, "Konkani, Kannada, English"),
    ("Pandurang Kamat", [3, 8, 9], 7, "Marathi, Kannada"),
    ("Uma Shankar Mishra", [1, 7], 3, "Hindi, English"),
    ("Rajendra Sutar", [5, 9, 4], 5, "Kannada, Marathi"),
]

AREAS: list[tuple[str, float, float]] = [
    ("Tilakwadi", 15.8422, 74.5039),
    ("Shahapur", 15.8638, 74.5137),
    ("Malmaruti", 15.8521, 74.4856),
    ("Sadashivnagar", 15.8595, 74.4959),
    ("Hanuman Nagar", 15.8411, 74.4856),
    ("Camp", 15.8565, 74.5054),
    ("Angol", 15.8299, 74.5054),
    ("Ashok Nagar", 15.8489, 74.5136),
    ("Channamma Nagar", 15.8497, 74.5234),
    ("Vivekananda Nagar", 15.8677, 74.4934),
]

LIFECYCLE = [
    TaskStatus.DRAFT,
    TaskStatus.PENDING_CONFIRMATION,
    TaskStatus.CONFIRMED,
    TaskStatus.SEARCHING_WORKER,
    TaskStatus.OFFERED,
    TaskStatus.ACCEPTED,
    TaskStatus.WORKER_ON_THE_WAY,
    TaskStatus.IN_PROGRESS,
    TaskStatus.COMPLETED,
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ago(days: float, hour: int | None = None) -> datetime:
    moment = _utcnow() - timedelta(days=days)
    if hour is not None:
        moment = moment.replace(hour=hour, minute=rng.choice([0, 15, 30, 45]), second=0, microsecond=0)
    return moment


def _jitter(lat: float, lng: float, spread: float = 0.004) -> tuple[float, float]:
    return round(lat + rng.uniform(-spread, spread), 6), round(lng + rng.uniform(-spread, spread), 6)


def _chain(final_status: str, cancel_from: str | None = None) -> list[str]:
    if cancel_from:
        idx = LIFECYCLE.index(cancel_from)
        return [s.value for s in LIFECYCLE[: idx + 1]] + [TaskStatus.CANCELLED.value]
    if final_status == TaskStatus.DISPUTED.value:
        return [s.value for s in LIFECYCLE] + [TaskStatus.DISPUTED.value]
    if final_status == TaskStatus.DRAFT.value:
        return [TaskStatus.DRAFT.value]
    idx = LIFECYCLE.index(TaskStatus(final_status))
    return [s.value for s in LIFECYCLE[: idx + 1]]


def _phone(i: int) -> str:
    return f"+919845{i:05d}"


def _make_users(db: Session) -> tuple[User, list[User], list[User]]:
    admin = User(
        email=ADMIN_EMAIL,
        phone=_phone(0),
        password_hash=hash_password(ADMIN_PASSWORD),
        full_name=ADMIN_NAME,
        role=UserRole.ADMIN.value,
        city=CITY,
        is_email_verified=True,
        created_at=_ago(90),
        last_login_at=_ago(0.2),
    )
    db.add(admin)
    db.flush()

    customers: list[User] = []
    for i, name in enumerate(CUSTOMERS, start=1):
        area_name, lat, lng = AREAS[i % len(AREAS)]
        user = User(
            email=f"customer{i}@demo.taskflex.dev",
            phone=_phone(i),
            password_hash=hash_password(DEMO_PASSWORD),
            full_name=name,
            role=UserRole.CUSTOMER.value,
            city=CITY,
            is_email_verified=True,
            created_at=_ago(80 - i * 4, hour=10),
            last_login_at=_ago(rng.uniform(0.1, 6)),
        )
        db.add(user)
        db.flush()
        db.add(
            CustomerProfile(
                user_id=user.id,
                address=f"{10 + i}th Cross, {area_name}, {CITY}",
                area=area_name,
                default_latitude=lat,
                default_longitude=lng,
                created_at=user.created_at,
            )
        )
        db.add_all(
            [
                SavedLocation(
                    user_id=user.id, label="Home", address=f"{10 + i}th Cross, {area_name}, {CITY}",
                    area=area_name, city=CITY, latitude=lat, longitude=lng, is_default=True,
                ),
                SavedLocation(
                    user_id=user.id, label="Work", address=f"Udyambag Industrial Area, {CITY}",
                    area="Udyambag", city=CITY, latitude=15.8233, longitude=74.4771, is_default=False,
                ),
            ]
        )
        customers.append(user)

    workers: list[User] = []
    for i, (name, skill_idx, years, langs) in enumerate(WORKERS, start=1):
        area_name, lat, lng = AREAS[(i * 3) % len(AREAS)]
        verified = i <= 16  # 16 verified, 4 pending verification
        wlat, wlng = _jitter(lat, lng)
        user = User(
            email=f"worker{i}@demo.taskflex.dev",
            phone=_phone(10 + i),
            password_hash=hash_password(DEMO_PASSWORD),
            full_name=name,
            role=UserRole.WORKER.value,
            city=CITY,
            is_email_verified=True,
            created_at=_ago(85 - i * 3, hour=9),
            last_login_at=_ago(rng.uniform(0.05, 3)),
        )
        db.add(user)
        db.flush()
        profile = WorkerProfile(
            user_id=user.id,
            bio=(
                f"{name.split()[0]} has been running errands in {CITY} for {years} year(s). "
                "Reliable, punctual and comfortable with government office paperwork."
                if verified
                else f"New runner on the TASKFLEX platform in {CITY}. Verification in progress."
            ),
            address=f"{area_name}, {CITY}",
            area=area_name,
            city=CITY,
            latitude=wlat,
            longitude=wlng,
            experience_years=years,
            languages=langs,
            is_online=verified and i % 5 != 4,  # most verified workers online
            is_verified=verified,
            verification_status=VerificationStatus.APPROVED.value if verified else VerificationStatus.PENDING.value,
            working_radius_km=rng.choice([5.0, 6.0, 8.0, 8.0, 10.0]),
            max_concurrent_tasks=rng.choice([1, 1, 2]),
            created_at=user.created_at,
        )
        db.add(profile)
        db.flush()
        for idx in skill_idx:
            skill = db.scalar(select(Skill).where(Skill.slug == SKILLS[idx][1]))
            db.add(WorkerSkill(worker_profile_id=profile.id, skill_id=skill.id, experience_level="experienced" if years >= 5 else "intermediate"))
        for day in range(7):
            db.add(
                WorkerAvailability(
                    worker_profile_id=profile.id,
                    day_of_week=day,
                    start_time=time(8, 0) if day != 6 else time(9, 0),
                    end_time=time(20, 0) if day != 6 else time(17, 0),
                    is_available=(day != 6) or (i % 3 == 0),
                )
            )
        doc_status = VerificationStatus.APPROVED.value if verified else VerificationStatus.PENDING.value
        db.add(
            VerificationDocument(
                worker_profile_id=profile.id,
                document_type="id_card",
                file_name=f"demo-id-{i}.jpg",
                file_path=f"uploads/verification/demo-id-{i}.jpg",
                mime_type="image/jpeg",
                file_size=rng.randint(120_000, 900_000),
                status=doc_status,
                reviewed_by_id=admin.id if verified else None,
                reviewed_at=_ago(70 - i * 2) if verified else None,
                created_at=user.created_at,
            )
        )
        workers.append(user)
    db.flush()
    return admin, customers, workers


def _add_history(db: Session, task: Task, actor_ids: dict[str, str], start: datetime) -> None:
    chain = _chain(task.status, cancel_from=task.status == TaskStatus.CANCELLED.value and "CONFIRMED")
    for pos, status in enumerate(chain):
        if pos == 0:
            actor, role = task.customer_id, "CUSTOMER"
        elif status in (TaskStatus.ACCEPTED.value, TaskStatus.WORKER_ON_THE_WAY.value, TaskStatus.IN_PROGRESS.value, TaskStatus.COMPLETED.value):
            actor, role = task.assigned_worker_id, "WORKER"
        elif status == TaskStatus.CANCELLED.value:
            actor, role = actor_ids["canceller"], actor_ids.get("canceller_role", "CUSTOMER")
        elif status == TaskStatus.DISPUTED.value:
            actor, role = task.customer_id, "CUSTOMER"
        else:
            actor, role = task.customer_id, "CUSTOMER"
        when = start + timedelta(hours=4 * pos + rng.randint(0, 3))
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=chain[pos - 1] if pos else None,
                to_status=status,
                changed_by_id=actor,
                changed_by_role=role,
                note=None,
                created_at=when,
            )
        )


def _add_task(
    db: Session,
    spec: dict,
    customers: list[User],
    workers: list[User],
) -> Task:
    customer = customers[spec["customer"]]
    worker_user = workers[spec["worker"]] if spec.get("worker") is not None else None
    area_name, lat, lng = AREAS[spec.get("area", spec["customer"] % len(AREAS))]
    tlat, tlng = _jitter(lat, lng)
    created = _ago(spec["days_ago"], hour=spec.get("hour", 10))
    sched_day = date.today() + timedelta(days=spec.get("in_days", 1))
    status = spec["status"]

    task = Task(
        customer_id=customer.id,
        title=spec["title"],
        description=spec["description"],
        task_type=spec["type"],
        status=status,
        urgency=spec.get("urgency", "normal"),
        scheduled_date=sched_day,
        scheduled_time=spec.get("scheduled_time", time(10, 30)),
        time_window_end=spec.get("time_window_end", time(12, 30)),
        estimated_duration_minutes=spec.get("minutes", 60),
        latitude=tlat,
        longitude=tlng,
        address_text=spec["address"],
        area_name=area_name,
        city=CITY,
        budget=spec["budget"],
        special_requirements=spec.get("special"),
        parsed_by_ai=True,
        ai_confidence=spec.get("confidence", round(rng.uniform(0.78, 0.96), 2)),
        raw_request_text=spec["raw"],
        assigned_worker_id=worker_user.id if worker_user else None,
        confirmed_at=created + timedelta(hours=2) if status not in (TaskStatus.DRAFT.value, TaskStatus.PENDING_CONFIRMATION.value) else None,
        payment_status="CAPTURED" if status == TaskStatus.COMPLETED.value else None,
        created_at=created,
        updated_at=_utcnow(),
    )
    if worker_user and status in (
        TaskStatus.WORKER_ON_THE_WAY.value, TaskStatus.IN_PROGRESS.value,
        TaskStatus.COMPLETED.value, TaskStatus.DISPUTED.value,
    ):
        task.worker_completed_at = created + timedelta(hours=30)
        task.customer_confirmed_at = created + timedelta(hours=32)
        task.completed_at = created + timedelta(hours=32)
    if status == TaskStatus.CANCELLED.value:
        task.cancelled_at = created + timedelta(hours=20)
        task.cancellation_reason = spec.get("cancel_reason", "Plans changed — no longer needed.")
    db.add(task)
    db.flush()

    for order, (slug, skill_name) in enumerate(spec["reqs"]):
        skill = db.scalar(select(Skill).where(Skill.slug == slug))
        db.add(
            TaskRequirement(
                task_id=task.id,
                skill_id=skill.id if skill else None,
                skill_name=skill_name,
                is_required=order == 0,
            )
        )
    db.add(
        TaskLocation(
            task_id=task.id, label="primary", sequence=0,
            latitude=tlat, longitude=tlng, address=spec["address"],
        )
    )

    _add_history(db, task, {"canceller": customer.id, "canceller_role": "CUSTOMER"}, created)

    if worker_user and status not in (TaskStatus.DRAFT.value, TaskStatus.PENDING_CONFIRMATION.value, TaskStatus.CONFIRMED.value, TaskStatus.SEARCHING_WORKER.value, TaskStatus.CANCELLED.value):
        db.add(
            TaskAssignment(
                task_id=task.id,
                worker_id=worker_user.id,
                status="COMPLETED" if status in (TaskStatus.COMPLETED.value, TaskStatus.DISPUTED.value) else "ACTIVE",
                accepted_at=created + timedelta(hours=8),
                started_at=created + timedelta(hours=26) if status in (TaskStatus.IN_PROGRESS.value, TaskStatus.COMPLETED.value, TaskStatus.DISPUTED.value) else None,
                completed_at=created + timedelta(hours=32) if status in (TaskStatus.COMPLETED.value, TaskStatus.DISPUTED.value) else None,
                earnings_amount=round(spec["budget"] * (1 - COMMISSION_PERCENT / 100), 2),
                commission_amount=round(spec["budget"] * COMMISSION_PERCENT / 100, 2),
                created_at=created + timedelta(hours=8),
            )
        )
    return task


def _seed_completed_task_extras(db: Session, task: Task, spec: dict, admin: User, worker_user: User) -> None:
    commission = round(spec["budget"] * COMMISSION_PERCENT / 100, 2)
    payout = round(spec["budget"] - commission, 2)
    captured = task.created_at + timedelta(hours=33)
    db.add(
        Payment(
            task_id=task.id,
            customer_id=task.customer_id,
            provider="mock",
            provider_reference=f"mock_pay_{task.id[:8]}",
            amount=float(spec["budget"]),
            commission_amount=commission,
            worker_payout_amount=payout,
            status="CAPTURED",
            authorized_at=captured - timedelta(minutes=3),
            captured_at=captured,
            created_at=captured,
        )
    )
    score = spec["rating"]
    db.add(
        Rating(
            task_id=task.id,
            rater_id=task.customer_id,
            ratee_id=worker_user.id,
            direction=RatingDirection.CUSTOMER_TO_WORKER.value,
            score=score,
            comment=spec["rating_comment"],
            created_at=captured + timedelta(hours=2),
        )
    )
    db.add(
        Review(
            task_id=task.id,
            author_id=task.customer_id,
            target_user_id=worker_user.id,
            rating_score=score,
            body=spec["rating_comment"],
            is_public=True,
            created_at=captured + timedelta(hours=2),
        )
    )
    if spec.get("worker_rated"):
        db.add(
            Rating(
                task_id=task.id,
                rater_id=worker_user.id,
                ratee_id=task.customer_id,
                direction=RatingDirection.WORKER_TO_CUSTOMER.value,
                score=spec["worker_rated"],
                comment="Clear instructions and prompt confirmation. Great customer.",
                created_at=captured + timedelta(hours=3),
            )
        )


def _seed_wallets_and_transactions(db: Session, customers: list[User], workers: list[User], completed_by_worker: dict[str, float]) -> None:
    for user in [*(customers), *(workers)]:
        db.add(Wallet(user_id=user.id, balance=0.0, created_at=user.created_at))
    db.flush()

    for i, user in enumerate(customers):
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
        db.add(
            Transaction(
                user_id=user.id, wallet_id=wallet.id, type=TransactionType.CREDIT.value,
                amount=2000.0, balance_after=2000.0, reference_type="topup",
                description="Demo wallet top-up", created_at=_ago(25 - (i % 10)),
            )
        )
        wallet.balance = 2000.0
    db.flush()

    for user in customers:
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
        spent = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.customer_id == user.id, Payment.status == "CAPTURED"
            )
        )
        tasks = db.scalars(
            select(Payment).where(Payment.customer_id == user.id, Payment.status == "CAPTURED").order_by(Payment.captured_at)
        ).all()
        balance = wallet.balance
        for payment in tasks:
            balance = round(balance - payment.amount, 2)
            db.add(
                Transaction(
                    user_id=user.id, wallet_id=wallet.id, type=TransactionType.DEBIT.value,
                    amount=payment.amount, balance_after=balance, reference_type="task",
                    reference_id=payment.task_id, description=f"Payment for task",
                    created_at=payment.captured_at,
                )
            )
        wallet.balance = balance
        wallet.total_spent = float(spent or 0.0)

    for user in workers:
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
        earned = completed_by_worker.get(user.id, 0.0)
        payments = (
            db.execute(
                select(Payment, Task)
                .join(Task, Task.id == Payment.task_id)
                .where(Task.assigned_worker_id == user.id, Payment.status == "CAPTURED")
                .order_by(Payment.captured_at)
            ).all()
        )
        balance = 0.0
        for payment, _task in payments:
            balance = round(balance + payment.worker_payout_amount, 2)
            db.add(
                Transaction(
                    user_id=user.id, wallet_id=wallet.id, type=TransactionType.PAYOUT.value,
                    amount=payment.worker_payout_amount, balance_after=balance,
                    reference_type="task", reference_id=payment.task_id,
                    description="Task payout after commission", created_at=payment.captured_at,
                )
            )
        wallet.balance = balance
        wallet.total_earned = earned


def _seed_conversations(db: Session, tasks: list[tuple[Task, dict]], workers: list[User]) -> None:
    scripts = [
        ["Hi! I've accepted your task. Where exactly should I meet the officer?",
         "Front desk, ask for the applications counter. I've added the reference number in task details.",
         "Got it. I'll carry a printout of the acknowledgement too."],
        ["Please call me if the queue looks longer than an hour.",
         "Sure. Currently about 25 people ahead, I'll keep you posted.",
         "Thanks! Payment released after completion, right?",
         "Yes — amount is captured only after you confirm completion."],
        ["The medicines total is ₹240, slightly over the budget. Proceed?",
         "Yes, go ahead. I'll adjust on confirmation."],
        ["I've reached the branch. Token number 34.",
         "Perfect, thank you! Please update the status when you're done."],
    ]
    for t_idx, (task, spec) in enumerate(tasks):
        if spec.get("worker") is None:
            continue
        worker_user = workers[spec["worker"]]
        conv = Conversation(
            task_id=task.id,
            customer_id=task.customer_id,
            worker_id=worker_user.id,
            last_message_at=task.created_at + timedelta(hours=10),
            created_at=task.created_at + timedelta(hours=8),
        )
        db.add(conv)
        db.flush()
        lines = scripts[t_idx % len(scripts)]
        for m_idx, body in enumerate(lines):
            sender = task.customer_id if m_idx % 2 == 0 else worker_user.id
            db.add(
                Message(
                    conversation_id=conv.id,
                    sender_id=sender,
                    body=body,
                    is_read=True,
                    read_at=task.created_at + timedelta(hours=12),
                    created_at=task.created_at + timedelta(hours=8, minutes=7 * m_idx),
                )
            )


def _seed_notifications(db: Session, tasks: list[tuple[Task, dict]], offers: list[TaskOffer]) -> None:
    for task, spec in tasks:
        if spec.get("worker") is not None:
            db.add(
                Notification(
                    user_id=task.customer_id,
                    type="WORKER_ACCEPTED",
                    title="A worker accepted your task",
                    body=f"Your task '{task.title}' has been accepted.",
                    data={"task_id": task.id},
                    link=f"/tasks/{task.id}",
                    is_read=spec["days_ago"] > 3,
                    read_at=task.created_at + timedelta(hours=1) if spec["days_ago"] > 3 else None,
                    created_at=task.created_at + timedelta(hours=8),
                )
            )
        if task.status == TaskStatus.COMPLETED.value:
            db.add(
                Notification(
                    user_id=task.assigned_worker_id,
                    type="PAYMENT_SUCCESSFUL",
                    title="Payment received",
                    body=f"Payout for '{task.title}' has been credited to your wallet.",
                    data={"task_id": task.id},
                    link="/wallet",
                    is_read=True,
                    read_at=task.created_at + timedelta(hours=40),
                    created_at=task.created_at + timedelta(hours=33),
                )
            )
    for offer in offers:
        db.add(
            Notification(
                user_id=offer.worker_id,
                type="TASK_OFFER",
                title="New task offer nearby",
                body=f"You have a new offer for '{offer.task.title}'. It expires soon!",
                data={"task_id": offer.task_id, "offer_id": offer.id},
                link="/offers",
                is_read=offer.status != "PENDING",
                created_at=offer.created_at,
            )
        )


def _seed_audit_logs(db: Session, admin: User, workers: list[User]) -> None:
    for i, user in enumerate(workers[:16]):
        db.add(
            AuditLog(
                user_id=admin.id,
                action="worker.verified",
                entity_type="verification_document",
                entity_id=user.id,
                ip_address="127.0.0.1",
                metadata_json={"worker": user.full_name},
                created_at=_ago(70 - i * 2, hour=11),
            )
        )
    db.add(
        AuditLog(
            user_id=admin.id,
            action="setting_updated",
            entity_type="system_setting",
            entity_id="platform_commission_percent",
            ip_address="127.0.0.1",
            metadata_json={"value": "10.0"},
            created_at=_ago(30, hour=9),
        )
    )


def _seed_system_settings(db: Session) -> None:
    rows = [
        ("platform_commission_percent", "10.0", "float", "Platform commission deducted from worker payout (%)"),
        ("default_worker_radius_km", "8.0", "float", "Default worker search radius (km)"),
        ("offer_ttl_minutes", "15", "int", "How long a task offer stays open for a worker (minutes)"),
        ("max_offers_per_task", "6", "int", "Maximum workers offered each task simultaneously"),
        ("min_task_budget", "50", "int", "Minimum allowed task budget (INR)"),
        ("max_task_budget", "100000", "int", "Maximum allowed task budget (INR)"),
        ("support_email", "support@taskflex.dev", "string", "Support contact shown in help pages"),
    ]
    for key, value, vtype, desc in rows:
        db.add(SystemSetting(key=key, value=value, value_type=vtype, description=desc))


TASK_SPECS: list[dict] = [
    # --- 6 COMPLETED (payments, ratings, reviews, wallets) ---
    dict(title="Stand in queue at RTO Belagavi for my driving licence renewal",
         description="Reach RTO Belagavi by 9:30 AM, take a token for licence renewal and hold my place. Call me when your number is 5 away. Carry the acknowledgement printout I will share.",
         type="government_office", urgency="high", budget=500.0, minutes=120,
         reqs=[("queue_standing", "Queue Standing"), ("government_office", "Government Office Work")],
         status=TaskStatus.COMPLETED.value, customer=0, worker=0, area=0, days_ago=12, hour=8,
         address="RTO Office, Hindwadi, Belagavi",
         raw="I need someone to stand in the RTO queue tomorrow morning for my DL renewal and call me before my turn.",
         rating=5, rating_comment="Reached on time and handled everything at the RTO smoothly. Excellent!", worker_rated=5),
    dict(title="Submit my TC application at Karnataka University office",
         description="Submit the transfer certificate application at the university office and collect the acknowledgement receipt. The form is already filled and signed.",
         type="document_submission", urgency="normal", budget=350.0, minutes=60,
         reqs=[("document_submission", "Document Submission")],
         status=TaskStatus.COMPLETED.value, customer=1, worker=1, area=1, days_ago=10, hour=11,
         address="Karnataka University Office, Belagavi",
         raw="Please submit my TC application at the university office tomorrow and bring back the receipt.",
         rating=4, rating_comment="Good work, small delay in updates but task done properly.", worker_rated=4),
    dict(title="Collect my medical reports from KLE Hospital front desk",
         description="Collect my blood test reports from the KLE Hospital records counter using the patient ID I share. Bring them to my home in Malmaruti.",
         type="document_collection", urgency="high", budget=300.0, minutes=60,
         reqs=[("document_collection", "Document Collection"), ("hospital_assistance", "Hospital Assistance")],
         status=TaskStatus.COMPLETED.value, customer=2, worker=2, area=2, days_ago=8, hour=16,
         address="KLE Dr. Prabhakar Kore Hospital, Belagavi",
         raw="My reports are ready at KLE hospital. Can someone collect them this evening and drop them home?",
         rating=5, rating_comment="Very polite and efficient. Would hire again."),
    dict(title="Pick up my parcel from DTDC Shahapur branch",
         description="Collect the parcel kept in my name at the DTDC Shahapur branch and deliver it to my flat. ID copy will be shared on chat.",
         type="parcel_collection", urgency="normal", budget=200.0, minutes=45,
         reqs=[("courier_pickup", "Courier & Parcel Pickup")],
         status=TaskStatus.COMPLETED.value, customer=3, worker=3, area=1, days_ago=6, hour=17,
         address="DTDC Courier, Shahapur, Belagavi",
         raw="Pick up my DTDC parcel from the Shahapur branch and bring it to my place today evening.",
         rating=5, rating_comment="Kept me updated the whole time. Superb service.", worker_rated=5),
    dict(title="Register my father at KLE hospital OPD tomorrow morning",
         description="Reach the hospital by 8 AM, register my father at the OPD counter, get the token and stay till the doctor calls. General medicine department.",
         type="appointment_assistance", urgency="urgent", budget=450.0, minutes=90,
         reqs=[("hospital_assistance", "Hospital Assistance"), ("queue_standing", "Queue Standing")],
         status=TaskStatus.COMPLETED.value, customer=4, worker=7, area=2, days_ago=4, hour=7,
         address="KLE Hospital OPD Block, Belagavi",
         raw="Need help registering my father at KLE hospital OPD at 8 AM tomorrow and holding his place in the queue.",
         rating=4, rating_comment="Task completed as promised. Communication could be quicker."),
    dict(title="Buy medicines from Apollo Pharmacy Tilakwadi and deliver home",
         description="Buy the medicines on the prescription photo I share from Apollo Pharmacy Tilakwadi and deliver to my address. Budget covers the bill; pay there and I confirm on delivery.",
         type="grocery_pickup", urgency="urgent", budget=250.0, minutes=45,
         reqs=[("grocery_pickup", "Grocery Pickup")],
         status=TaskStatus.COMPLETED.value, customer=5, worker=4, area=0, days_ago=2, hour=19,
         address="Apollo Pharmacy, Tilakwadi, Belagavi",
         raw="Urgent! Someone please buy my father's medicines from Apollo Tilakwadi and deliver home tonight.",
         rating=3, rating_comment="Work got done but arrived later than the scheduled window."),
    # --- 3 IN_PROGRESS ---
    dict(title="Update passbook at SBI Camp branch",
         description="Get my SBI passbook updated at the Camp branch and share a photo of the updated page. Passbook is in an envelope with the branch manager's desk noted on it.",
         type="bank_assistance", urgency="normal", budget=300.0, minutes=60,
         reqs=[("bank_assistance", "Bank Assistance")],
         status=TaskStatus.IN_PROGRESS.value, customer=6, worker=6, area=5, days_ago=1, hour=10,
         address="SBI Camp Branch, Belagavi",
         raw="Someone please update my passbook at the SBI Camp branch today."),
    dict(title="Stand in queue at Belagavi Municipal Corporation for property tax receipt",
         description="Hold my place in the property tax counter queue at the CMC office. I will join before payment. Token starts at 10 AM.",
         type="queue_standing", urgency="high", budget=400.0, minutes=150,
         reqs=[("queue_standing", "Queue Standing")],
         status=TaskStatus.IN_PROGRESS.value, customer=7, worker=12, area=5, days_ago=0.5, hour=9,
         address="Belagavi City Corporation, Clock Tower",
         raw="Need someone to stand in the property tax queue at CMC office from 10 AM today."),
    dict(title="Collect my college transcripts from VTU regional office",
         description="Collect the sealed transcript envelope from the VTU regional office counter against the fee receipt I share. Keep the envelope sealed at all times.",
         type="document_collection", urgency="normal", budget=400.0, minutes=120,
         reqs=[("document_collection", "Document Collection")],
         status=TaskStatus.IN_PROGRESS.value, customer=8, worker=16, area=9, days_ago=0.2, hour=14,
         address="VTU Regional Office, Belagavi",
         raw="Please collect my transcripts from the VTU office this afternoon and keep them sealed."),
    # --- 2 WORKER_ON_THE_WAY ---
    dict(title="Deliver my passport application to Passport Seva Kendra",
         description="Drop the sealed passport application envelope at the PSK drop box before 4 PM and share a photo of the drop receipt.",
         type="document_submission", urgency="high", budget=450.0, minutes=90,
         reqs=[("document_submission", "Document Submission"), ("government_office", "Government Office Work")],
         status=TaskStatus.WORKER_ON_THE_WAY.value, customer=9, worker=0, area=5, days_ago=0.1, hour=13,
         address="Passport Seva Kendra, Camp, Belagavi",
         raw="My passport application needs to reach the PSK drop box before 4 PM today."),
    dict(title="Pick up grocery order from Reliance Fresh Angol",
         description="Collect the ready grocery order at the Angol store counter and deliver home. The bill is already paid online.",
         type="grocery_pickup", urgency="normal", budget=220.0, minutes=45,
         reqs=[("grocery_pickup", "Grocery Pickup")],
         status=TaskStatus.WORKER_ON_THE_WAY.value, customer=0, worker=4, area=6, days_ago=0.05, hour=18,
         address="Reliance Fresh, Angol, Belagavi",
         raw="Collect my paid grocery order from Reliance Fresh Angol in 30 minutes and bring it over."),
    # --- 2 ACCEPTED ---
    dict(title="Submit scholarship form at DC office before 5 PM",
         description="Submit the signed scholarship form at the DC office submission window and photograph the stamped acknowledgement.",
         type="form_submission", urgency="urgent", budget=380.0, minutes=75,
         reqs=[("form_submission", "Form Filling"), ("government_office", "Government Office Work")],
         status=TaskStatus.ACCEPTED.value, customer=1, worker=11, area=5, days_ago=0.05, hour=15,
         address="Deputy Commissioner's Office, Belagavi",
         raw="Urgent: submit my scholarship form at the DC office before they close at 5 today."),
    dict(title="Collect 50 printouts from Sri Digital Prints, Camp",
         description="Collect 50 A4 printouts already emailed to the shop and bring them to Sadashivnagar.",
         type="local_errand", urgency="low", budget=180.0, minutes=40,
         reqs=[("local_errand", "Local Errands")],
         status=TaskStatus.ACCEPTED.value, customer=2, worker=14, area=5, days_ago=0.03, hour=16,
         address="Sri Digital Prints, Camp, Belagavi",
         raw="Collect my printouts from the Camp copy shop and drop them at my place."),
    # --- 3 OFFERED (pending offers) ---
    dict(title="Stand in token queue at RTO for vehicle ownership transfer",
         description="Take a token at the RTO vehicle transfer counter around 10:30 AM and hold my place until I arrive with the documents.",
         type="queue_standing", urgency="normal", budget=420.0, minutes=120,
         reqs=[("queue_standing", "Queue Standing")],
         status=TaskStatus.OFFERED.value, customer=3, worker=None, area=0, days_ago=0.02, hour=9,
         address="RTO Office, Hindwadi, Belagavi",
         raw="Hold my spot in the RTO vehicle transfer queue tomorrow at 10:30.",
         offers=[(8, 0.91), (13, 0.87)]),
    dict(title="Collect repaired spectacles from Lawrence & Mayo, Camp",
         description="Collect my repaired spectacles against the token slip photo I share and deliver to Hanuman Nagar.",
         type="local_errand", urgency="low", budget=200.0, minutes=45,
         reqs=[("local_errand", "Local Errands")],
         status=TaskStatus.OFFERED.value, customer=4, worker=None, area=5, days_ago=0.03, hour=12,
         address="Lawrence & Mayo Opticians, Camp, Belagavi",
         raw="Someone please pick up my spectacles from the Camp optician shop tomorrow.",
         offers=[(3, 0.88)]),
    dict(title="Bank challan submission at Canara Bank Tilakwadi",
         description="Submit the filled challan at the cash counter, collect the stamped copy and share a clear photo of it.",
         type="bank_assistance", urgency="high", budget=320.0, minutes=60,
         reqs=[("bank_assistance", "Bank Assistance")],
         status=TaskStatus.OFFERED.value, customer=5, worker=None, area=0, days_ago=0.04, hour=11,
         address="Canara Bank, Tilakwadi, Belagavi",
         raw="Need someone to submit a challan at Canara Bank Tilakwadi tomorrow forenoon.",
         offers=[(6, 0.93), (10, 0.84), (19, 0.8)]),
    # --- 2 SEARCHING_WORKER ---
    dict(title="Aadhaar enrolment appointment assistance for my grandmother",
         description="Accompany my grandmother to the Aadhaar centre, manage token and forms, and stay till biometrics are done. Kannada speaking preferred.",
         type="appointment_assistance", urgency="high", budget=500.0, minutes=120,
         reqs=[("government_office", "Government Office Work"), ("queue_standing", "Queue Standing")],
         status=TaskStatus.SEARCHING_WORKER.value, customer=6, worker=None, area=3, days_ago=0.08, hour=10,
         address="Aadhaar Seva Kendra, Sadashivnagar, Belagavi",
         raw="My grandmother needs help at the Aadhaar centre this week — token, forms and queue.",
         confidence=0.74),
    dict(title="Collect demand draft details from KLE Society office",
         description="Visit the KLE Society office, collect the DD application slip after verification and courier it to my address.",
         type="document_collection", urgency="normal", budget=350.0, minutes=90,
         reqs=[("document_collection", "Document Collection")],
         status=TaskStatus.SEARCHING_WORKER.value, customer=7, worker=None, area=9, days_ago=0.07, hour=12,
         address="KLE Society Head Office, Belagavi",
         raw="Need a runner to collect a DD slip from KLE Society office and post it to me."),
    # --- 3 CONFIRMED ---
    dict(title="Weekend grocery run from D-Mart Gokak Road",
         description="Pick up my pre-paid D-Mart order Saturday evening and deliver home. Order slip will be shared on chat.",
         type="grocery_pickup", urgency="low", budget=260.0, minutes=60,
         reqs=[("grocery_pickup", "Grocery Pickup")],
         status=TaskStatus.CONFIRMED.value, customer=8, worker=9, area=6, days_ago=0.1, hour=17, in_days=2,
         address="D-Mart, Gokak Road, Belagavi",
         raw="Pick up my D-Mart order on Saturday evening and bring it home."),
    dict(title="Courier submission at Bluedart Shahapur for business documents",
         description="Book and pay for an outbound Bluedart shipment of business documents and share the tracking number photo.",
         type="courier_pickup", urgency="normal", budget=240.0, minutes=45,
         reqs=[("courier_pickup", "Courier & Parcel Pickup")],
         status=TaskStatus.CONFIRMED.value, customer=9, worker=10, area=1, days_ago=0.12, hour=11, in_days=1,
         address="Bluedart Express, Shahapur, Belagavi",
         raw="Send a courier of documents from Bluedart Shahapur tomorrow morning."),
    dict(title="Hospital queue token for cardiology OPD early morning",
         description="Take the first cardiology OPD token at 7:30 AM and hold my place till I arrive by 8:45.",
         type="queue_standing", urgency="urgent", budget=480.0, minutes=120,
         reqs=[("queue_standing", "Queue Standing"), ("hospital_assistance", "Hospital Assistance")],
         status=TaskStatus.CONFIRMED.value, customer=0, worker=2, area=2, days_ago=0.15, hour=7, in_days=1,
         address="KLE Hospital Cardiology OPD, Belagavi",
         raw="I need the first cardiology token at KLE hospital tomorrow. Be there by 7:30 AM."),
    # --- 3 PENDING_CONFIRMATION ---
    dict(title="Marriage certificate application drop-off at Sub-Registrar Office",
         description="Drop the completed marriage certificate application at the sub-registrar office and collect the acknowledgement.",
         type="document_submission", urgency="normal", budget=400.0, minutes=90,
         reqs=[("document_submission", "Document Submission"), ("government_office", "Government Office Work")],
         status=TaskStatus.PENDING_CONFIRMATION.value, customer=1, worker=None, area=5, days_ago=0.2, hour=10, in_days=3,
         address="Sub-Registrar Office, Belagavi",
         raw="Drop my marriage certificate application at the sub-registrar office this week.", confidence=0.81),
    dict(title="Pick up textbooks from Bhagya Book House for my sister",
         description="Buy the two textbooks on the list I share from Bhagya Book House and deliver home. Budget includes bill amount.",
         type="local_errand", urgency="low", budget=190.0, minutes=45,
         reqs=[("local_errand", "Local Errands")],
         status=TaskStatus.PENDING_CONFIRMATION.value, customer=3, worker=None, area=9, days_ago=0.25, hour=15, in_days=2,
         address="Bhagya Book House, Vivekananda Nagar, Belagavi",
         raw="Buy two textbooks from Bhagya Book House and drop them at my place.", confidence=0.69),
    dict(title="Queue spot at KSRTC counter for bus pass renewal",
         description="Hold my place at the KSRTC bus pass renewal counter from 10 AM; I will join before the counter closes for lunch.",
         type="queue_standing", urgency="normal", budget=300.0, minutes=90,
         reqs=[("queue_standing", "Queue Standing")],
         status=TaskStatus.PENDING_CONFIRMATION.value, customer=4, worker=None, area=5, days_ago=0.3, hour=9, in_days=1,
         address="KSRTC Bus Stand, Belagavi",
         raw="Need my spot held in the KSRTC pass queue tomorrow 10 AM.", confidence=0.77),
    # --- 2 DRAFT ---
    dict(title="Deliver tiffin boxes from home to office at Udyambag",
         description="Pick up three tiffin boxes from my home at 12:30 PM and deliver to the office reception at Udyambag.",
         type="office_errand", urgency="normal", budget=280.0, minutes=60,
         reqs=[("local_errand", "Local Errands")],
         status=TaskStatus.DRAFT.value, customer=5, worker=None, area=0, days_ago=0.4, hour=12, in_days=1,
         address="Udyambag Industrial Area, Belagavi",
         raw="Deliver my home-made tiffins to my Udyambag office at lunch.", confidence=0.58),
    dict(title="Collect laptop from service centre Vivekananda Nagar",
         description="Collect my repaired laptop from the Dell service centre against the job sheet and bring it home carefully.",
         type="parcel_collection", urgency="high", budget=350.0, minutes=60,
         reqs=[("courier_pickup", "Courier & Parcel Pickup")],
         status=TaskStatus.DRAFT.value, customer=6, worker=None, area=9, days_ago=0.5, hour=18, in_days=2,
         address="Dell Service Centre, Vivekananda Nagar, Belagavi",
         raw="Collect my laptop from the Dell service centre once it's ready.", confidence=0.62),
    # --- 3 CANCELLED ---
    dict(title="Submit gas agency documents and collect new connection papers",
         description="Submit the KYC documents at the gas agency office and collect the new connection acknowledgement.",
         type="document_submission", urgency="normal", budget=330.0, minutes=75,
         reqs=[("document_submission", "Document Submission")],
         status=TaskStatus.CANCELLED.value, customer=7, worker=17, area=3, days_ago=9, hour=10,
         address="HP Gas Agency, Sadashivnagar, Belagavi",
         raw="Submit my gas agency KYC papers and bring the acknowledgement.",
         cancel_reason="Resolved directly with the agency — cancelled by customer."),
    dict(title="Stand in queue at CESC office for new meter application",
         description="Take a token at the CESC new meter counter at 10 AM and hold my place till the documents are verified.",
         type="queue_standing", urgency="high", budget=400.0, minutes=120,
         reqs=[("queue_standing", "Queue Standing")],
         status=TaskStatus.CANCELLED.value, customer=8, worker=None, area=5, days_ago=7, hour=9,
         address="CESC Office, Belagavi",
         raw="Hold my place in the CESC meter application queue next Monday.",
         cancel_reason="Office holiday announced for that day."),
    dict(title="Pick up birthday cake from Monginis Camp at 6 PM",
         description="Collect the pre-ordered cake from Monginis Camp at 6 PM sharp and deliver home undamaged.",
         type="grocery_pickup", urgency="high", budget=250.0, minutes=45,
         reqs=[("grocery_pickup", "Grocery Pickup")],
         status=TaskStatus.CANCELLED.value, customer=9, worker=None, area=5, days_ago=5, hour=17,
         address="Monginis, Camp, Belagavi",
         raw="Pick up my ordered cake from Monginis Camp at 6 PM today.",
         cancel_reason="Party postponed — cake reordered for next week."),
    # --- 1 DISPUTED (completed task disputed by customer) ---
    dict(title="Collect land records from Tahsildar Office",
         description="Collect the certified land record copies from the Tahsildar office records room against the application number.",
         type="document_collection", urgency="high", budget=450.0, minutes=90,
         reqs=[("document_collection", "Document Collection")],
         status=TaskStatus.DISPUTED.value, customer=2, worker=13, area=5, days_ago=3, hour=10,
         address="Tahsildar Office, Belagavi",
         raw="Collect my certified land records from the Tahsildar office this week.",
         rating=2, rating_comment="Copies collected were incomplete; had to visit again myself.",
         dispute=dict(reason="SERVICE_QUALITY", description="The collected land record copies were missing two pages. I had to visit the office again myself. Requesting partial refund.")),
]


def seed_demo_data(db: Session) -> dict:
    """Populate the database with the deterministic demo dataset. Assumes empty tables."""
    for name, slug, category, desc in SKILLS:
        db.add(Skill(name=name, slug=slug, category=category, description=desc))
    db.flush()

    admin, customers, workers = _make_users(db)

    created_tasks: list[tuple[Task, dict]] = []
    completed_by_worker: dict[str, float] = {}
    all_offers: list[TaskOffer] = []

    for spec in TASK_SPECS:
        task = _add_task(db, spec, customers, workers)
        worker_user = workers[spec["worker"]] if spec.get("worker") is not None else None

        # Offers
        if spec.get("offers"):
            for worker_idx, score in spec["offers"]:
                offer = TaskOffer(
                    task_id=task.id,
                    worker_id=workers[worker_idx].id,
                    status="PENDING",
                    match_score=score,
                    match_breakdown=None,
                    expires_at=_utcnow() + timedelta(minutes=15),
                    created_at=task.created_at + timedelta(hours=1),
                )
                db.add(offer)
                all_offers.append(offer)
        elif worker_user and task.status not in (
            TaskStatus.DRAFT.value, TaskStatus.PENDING_CONFIRMATION.value,
            TaskStatus.CONFIRMED.value, TaskStatus.SEARCHING_WORKER.value,
        ):
            accepted = TaskOffer(
                task_id=task.id,
                worker_id=worker_user.id,
                status="ACCEPTED",
                match_score=0.92,
                expires_at=task.created_at + timedelta(hours=1),
                responded_at=task.created_at + timedelta(minutes=50),
                created_at=task.created_at + timedelta(hours=1),
            )
            db.add(accepted)
            all_offers.append(accepted)

        if task.status == TaskStatus.COMPLETED.value:
            _seed_completed_task_extras(db, task, spec, admin, worker_user)
            completed_by_worker[worker_user.id] = round(
                completed_by_worker.get(worker_user.id, 0.0) + spec["budget"] * (1 - COMMISSION_PERCENT / 100), 2
            )
        created_tasks.append((task, spec))

    # Dispute for the DISPUTED task
    for task, spec in created_tasks:
        if spec["status"] == TaskStatus.DISPUTED.value:
            worker_user = workers[spec["worker"]]
            db.add(
                Dispute(
                    task_id=task.id,
                    raised_by_id=task.customer_id,
                    against_id=worker_user.id,
                    reason=spec["dispute"]["reason"],
                    description=spec["dispute"]["description"],
                    status="OPEN",
                    created_at=task.created_at + timedelta(hours=40),
                )
            )

    _seed_conversations(db, created_tasks, workers)
    _seed_wallets_and_transactions(db, customers, workers, completed_by_worker)
    _seed_notifications(db, created_tasks, all_offers)
    _seed_audit_logs(db, admin, workers)
    _seed_system_settings(db)

    # Sync denormalised worker stats
    for idx, worker_user in enumerate(workers):
        profile = db.scalar(select(WorkerProfile).where(WorkerProfile.user_id == worker_user.id))
        completed = sum(
            1 for t, s in created_tasks
            if s.get("worker") is not None and workers[s["worker"]].id == worker_user.id
            and t.status in (TaskStatus.COMPLETED.value, TaskStatus.DISPUTED.value)
        )
        cancelled = sum(
            1 for t, s in created_tasks
            if s.get("worker") is not None and workers[s["worker"]].id == worker_user.id
            and t.status == TaskStatus.CANCELLED.value
        )
        ratings = db.scalars(
            select(Rating).where(Rating.ratee_id == worker_user.id, Rating.direction == RatingDirection.CUSTOMER_TO_WORKER.value)
        ).all()
        if profile.is_verified:
            # Blend this dataset's ratings with synthetic history so veteran
            # profiles look plausible in the demo UI.
            hist_count = rng.randint(4, 45)
            hist_avg = round(rng.uniform(4.0, 4.8), 2)
            if ratings:
                real_avg = sum(r.score for r in ratings) / len(ratings)
                profile.rating_count = len(ratings) + hist_count
                profile.rating_average = round(
                    (real_avg * len(ratings) + hist_avg * hist_count) / profile.rating_count, 2
                )
            else:
                profile.rating_average = hist_avg
                profile.rating_count = hist_count
        profile.completed_tasks_count = completed + rng.randint(3, 40)
        profile.cancelled_tasks_count = cancelled
        profile.total_earnings = completed_by_worker.get(worker_user.id, 0.0)

    db.flush()
    summary = {
        "admins": 1,
        "customers": len(customers),
        "workers": len(workers),
        "skills": len(SKILLS),
        "tasks": len(created_tasks),
        "offers": len(all_offers),
        "payments": sum(1 for t, s in created_tasks if s["status"] == TaskStatus.COMPLETED.value),
    }
    logger.info("demo_seed_complete", extra_fields=summary)
    return summary


def main() -> None:
    from app.db.init_db import init_db
    from app.db.session import SessionLocal

    init_db()
    db = SessionLocal()
    try:
        summary = seed_demo_data(db)
        db.commit()
        print(f"Seeded TASKFLEX demo data: {summary}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
