from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import CustomerProfile, Skill, User, Wallet, WorkerProfile, WorkerSkill


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.execute(select(User).where(func.lower(User.email) == email.lower())).scalar_one_or_none()

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_by_phone(self, phone: str) -> User | None:
        # Accounts may be stored as "+91XXXXXXXXXX" or a bare 10-digit local
        # number; match the entered number against both representations.
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return None
        candidates = {digits, f"+{digits}"}
        if digits.startswith("91") and len(digits) > 10:
            local = digits[2:]
            candidates |= {local, f"+{local}"}
        else:
            candidates |= {f"91{digits}", f"+91{digits}"}
        return (
            self.db.execute(select(User).where(User.phone.in_(candidates)).order_by(User.id))
            .scalars()
            .first()
        )

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def phone_exists(self, phone: str) -> bool:
        stmt = select(func.count()).select_from(User).where(User.phone == phone)
        return self.db.execute(stmt).scalar_one() > 0

    def create(self, **fields) -> User:
        user = User(**fields)
        self.db.add(user)
        self.db.flush()
        return user

    def create_customer_profile(self, user_id: str) -> CustomerProfile:
        profile = CustomerProfile(user_id=user_id)
        self.db.add(profile)
        self.db.flush()
        return profile

    def create_wallet(self, user_id: str) -> Wallet:
        wallet = Wallet(user_id=user_id)
        self.db.add(wallet)
        self.db.flush()
        return wallet

    def search_users(
        self, *, role: str | None = None, search: str | None = None, is_active: bool | None = None,
        page: int = 1, page_size: int = 20,
    ) -> tuple[list[User], int]:
        stmt = select(User).options(selectinload(User.customer_profile), selectinload(User.worker_profile))
        if role:
            stmt = stmt.where(User.role == role)
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
        stmt = stmt.order_by(User.created_at.desc())
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = self.db.execute(count_stmt).scalar_one()
        users = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(users), total

    # ---- worker-specific ----

    def get_worker_profile(self, user_id: str) -> WorkerProfile | None:
        return self.db.execute(
            select(WorkerProfile)
            .where(WorkerProfile.user_id == user_id)
            .options(selectinload(WorkerProfile.skills).selectinload(WorkerSkill.skill),
                     selectinload(WorkerProfile.availability))
        ).scalar_one_or_none()

    def get_worker_profile_by_id(self, profile_id: str) -> WorkerProfile | None:
        return self.db.execute(
            select(WorkerProfile)
            .where(WorkerProfile.id == profile_id)
            .options(selectinload(WorkerProfile.user), selectinload(WorkerProfile.skills).selectinload(WorkerSkill.skill))
        ).scalar_one_or_none()

    def create_worker_profile(self, user_id: str, **fields) -> WorkerProfile:
        profile = WorkerProfile(user_id=user_id, **fields)
        self.db.add(profile)
        self.db.flush()
        return profile

    def touch_last_login(self, user: User) -> None:
        user.last_login_at = datetime.now(timezone.utc)
        self.db.flush()

    # ---- skills ----

    def list_skills(self) -> list[Skill]:
        return list(self.db.execute(select(Skill).order_by(Skill.name)).scalars().all())

    def get_skills_by_slugs(self, slugs: list[str]) -> list[Skill]:
        if not slugs:
            return []
        return list(self.db.execute(select(Skill).where(Skill.slug.in_(slugs))).scalars().all())

    def set_worker_skills(self, profile: WorkerProfile, slugs: list[str]) -> None:
        skills = self.get_skills_by_slugs(slugs)
        profile.skills = [WorkerSkill(worker_profile_id=profile.id, skill_id=s.id) for s in skills]
        self.db.flush()
