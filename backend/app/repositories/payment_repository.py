from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, Dispute, Payment, SystemSetting, Transaction, Wallet


class PaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_wallet(self, user_id: str) -> Wallet | None:
        return self.db.execute(select(Wallet).where(Wallet.user_id == user_id)).scalar_one_or_none()

    def get_wallet_for_update(self, user_id: str) -> Wallet | None:
        stmt = select(Wallet).where(Wallet.user_id == user_id).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def ensure_wallet(self, user_id: str) -> Wallet:
        wallet = self.get_wallet(user_id)
        if wallet is None:
            wallet = Wallet(user_id=user_id)
            self.db.add(wallet)
            self.db.flush()
        return wallet

    def add_transaction(self, **fields) -> Transaction:
        tx = Transaction(**fields)
        self.db.add(tx)
        self.db.flush()
        return tx

    def transactions_for(self, user_id: str, page: int = 1, page_size: int = 20):
        stmt = select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total

    def transactions_between(self, user_id: str, start, end) -> list[Transaction]:
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.created_at >= start,
                Transaction.created_at < end,
            )
            .order_by(Transaction.created_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_payment(self, payment: Payment) -> Payment:
        self.db.add(payment)
        self.db.flush()
        return payment

    def payments_for(self, user_id: str, page: int = 1, page_size: int = 20):
        stmt = select(Payment).where(Payment.customer_id == user_id).order_by(Payment.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total

    def payment_for_task(self, task_id: str, *, purpose: str = "TASK") -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.task_id == task_id, Payment.purpose == purpose)
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def payments_for_task(self, task_id: str, *, purposes: tuple[str, ...] | None = None) -> list[Payment]:
        stmt = select(Payment).where(Payment.task_id == task_id)
        if purposes:
            stmt = stmt.where(Payment.purpose.in_(purposes))
        stmt = stmt.order_by(Payment.created_at)
        return list(self.db.execute(stmt).scalars().all())

    def payment_by_reference(self, reference: str) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.provider_reference == reference)
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def all_payments(self, page: int = 1, page_size: int = 20, status: str | None = None):
        stmt = select(Payment).options(selectinload(Payment.task))
        if status:
            stmt = stmt.where(Payment.status == status)
        stmt = stmt.order_by(Payment.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total

    def all_transactions(self, page: int = 1, page_size: int = 20, search: str | None = None):
        stmt = select(Transaction)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(func.lower(Transaction.description).like(like))
        stmt = stmt.order_by(Transaction.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total


class DisputeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, dispute_id: str) -> Dispute | None:
        return self.db.get(Dispute, dispute_id)

    def add(self, dispute: Dispute) -> Dispute:
        self.db.add(dispute)
        self.db.flush()
        return dispute

    def open_for_task(self, task_id: str) -> Dispute | None:
        stmt = select(Dispute).where(Dispute.task_id == task_id, Dispute.status.in_(["OPEN", "UNDER_REVIEW"]))
        return self.db.execute(stmt).scalar_one_or_none()

    def for_user(self, user_id: str) -> list[Dispute]:
        stmt = (
            select(Dispute)
            .where((Dispute.raised_by_id == user_id) | (Dispute.against_id == user_id))
            .order_by(Dispute.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def all_disputes(self, page: int = 1, page_size: int = 20, status: str | None = None):
        stmt = select(Dispute)
        if status:
            stmt = stmt.where(Dispute.status == status)
        stmt = stmt.order_by(Dispute.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log(self, **fields) -> AuditLog:
        entry = AuditLog(**fields)
        self.db.add(entry)
        self.db.flush()
        return entry

    def recent(self, page: int = 1, page_size: int = 20, action: str | None = None):
        stmt = select(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        stmt = stmt.order_by(AuditLog.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total


class SettingsRepository:
    DEFAULTS = {
        "platform_commission_percent": ("10.0", "float", "Platform commission deducted from worker payout (%)"),
        "default_worker_radius_km": ("8.0", "float", "Default worker search radius (km)"),
        "offer_ttl_minutes": ("15", "int", "How long a task offer stays open for a worker (minutes)"),
        "max_offers_per_task": ("6", "int", "Maximum workers offered each task simultaneously"),
        "min_task_budget": ("50", "int", "Minimum allowed task budget (INR)"),
        "max_task_budget": ("100000", "int", "Maximum allowed task budget (INR)"),
    }

    def __init__(self, db: Session):
        self.db = db

    def all_settings(self) -> dict[str, dict]:
        result = {
            key: {"value": value, "value_type": vtype, "description": desc}
            for key, (value, vtype, desc) in self.DEFAULTS.items()
        }
        for row in self.db.execute(select(SystemSetting)).scalars().all():
            result[row.key] = {"value": row.value, "value_type": row.value_type, "description": row.description}
        return result

    def get_value(self, key: str, cast: type = float):
        raw = self.all_settings().get(key, {}).get("value")
        if raw is None:
            return None
        try:
            if cast is bool:
                return raw.lower() in ("1", "true", "yes")
            return cast(raw)
        except (TypeError, ValueError):
            return None

    def set_value(self, key: str, value: str) -> SystemSetting:
        existing = self.db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
        if existing:
            existing.value = value
            self.db.flush()
            return existing
        row = SystemSetting(key=key, value=value, value_type="string")
        self.db.add(row)
        self.db.flush()
        return row
