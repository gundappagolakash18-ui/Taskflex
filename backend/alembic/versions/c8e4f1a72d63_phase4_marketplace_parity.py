"""Phase 4 commercial marketplace parity: bids, quests, payouts, affinities, RideCheck.

Revision ID: c8e4f1a72d63
Revises: f6a2b9d41e83
"""

from alembic import op
import sqlalchemy as sa

revision = "c8e4f1a72d63"
down_revision = "f6a2b9d41e83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Task columns: tips, scheduling, round trips, bidding window ---
    op.add_column(
        "tasks",
        sa.Column("tip_amount", sa.Numeric(precision=10, scale=2), server_default="0", nullable=False),
    )
    op.add_column(
        "tasks", sa.Column("is_scheduled", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("tasks", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("worker_confirmed_readiness", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "tasks", sa.Column("is_round_trip", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("tasks", sa.Column("return_otp_hash", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("return_otp_display", sa.String(length=4), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("return_otp_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("tasks", sa.Column("return_otp_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("return_otp_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("bids_close_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_tasks_scheduled_for"), "tasks", ["scheduled_for"], unique=False)

    # --- Worker profile columns: chaining, tier, UPI ---
    op.add_column(
        "worker_profiles",
        sa.Column("tier", sa.String(length=20), server_default="SILVER", nullable=False),
    )
    op.add_column(
        "worker_profiles",
        sa.Column("commission_rate", sa.Float(), server_default="0.1", nullable=False),
    )
    op.add_column("worker_profiles", sa.Column("queued_task_id", sa.String(), nullable=True))
    op.add_column(
        "worker_profiles",
        sa.Column("wrapping_up_soon", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("worker_profiles", sa.Column("upi_id", sa.String(length=120), nullable=True))
    op.add_column("worker_profiles", sa.Column("last_online_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_worker_profiles_queued_task_id_tasks",
        "worker_profiles",
        "tasks",
        ["queued_task_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- Counter-offer bids ---
    op.create_table(
        "task_bids",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("proposed_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("note", sa.String(length=140), nullable=True),
        sa.Column("estimated_arrival_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_bids_created_at"), "task_bids", ["created_at"], unique=False)
    op.create_index(op.f("ix_task_bids_status"), "task_bids", ["status"], unique=False)
    op.create_index("ix_task_bids_task_status", "task_bids", ["task_id", "status"], unique=False)
    op.create_index("ix_task_bids_worker", "task_bids", ["worker_id"], unique=False)

    # --- Quests ---
    op.create_table(
        "worker_quests",
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_tasks_count", sa.Integer(), nullable=False),
        sa.Column("bonus_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("valid_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_worker_quests_created_at"), "worker_quests", ["created_at"], unique=False)
    op.create_index("ix_worker_quests_active_date", "worker_quests", ["is_active", "valid_date"], unique=False)

    op.create_table(
        "worker_quest_progress",
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("quest_id", sa.String(), nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_claimed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["worker_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quest_id"], ["worker_quests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", "quest_id", name="uq_worker_quest"),
    )
    op.create_index(
        op.f("ix_worker_quest_progress_created_at"), "worker_quest_progress", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_worker_quest_progress_quest_id"), "worker_quest_progress", ["quest_id"], unique=False
    )

    # --- Instant UPI payouts ---
    op.create_table(
        "payout_requests",
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("upi_id", sa.String(length=120), nullable=False),
        sa.Column("reference_utr", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PROCESSING", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["worker_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_utr"),
    )
    op.create_index(op.f("ix_payout_requests_created_at"), "payout_requests", ["created_at"], unique=False)
    op.create_index(op.f("ix_payout_requests_status"), "payout_requests", ["status"], unique=False)
    op.create_index(
        "ix_payout_requests_worker_created", "payout_requests", ["worker_id", "created_at"], unique=False
    )

    # --- Customer affinities ---
    op.create_table(
        "customer_worker_affinities",
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("affinity_type", sa.String(length=20), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "worker_id", name="uq_customer_worker_affinity"),
    )
    op.create_index(
        op.f("ix_customer_worker_affinities_created_at"),
        "customer_worker_affinities",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_affinity_worker_type", "customer_worker_affinities", ["worker_id", "affinity_type"], unique=False
    )

    # --- RideCheck safety events ---
    op.create_table(
        "ridecheck_events",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("deviation_m", sa.Float(), nullable=True),
        sa.Column("stationary_seconds", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgment_reason", sa.String(length=120), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_flagged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ridecheck_events_created_at"), "ridecheck_events", ["created_at"], unique=False)
    op.create_index("ix_ridecheck_task_status", "ridecheck_events", ["task_id", "status"], unique=False)
    op.create_index("ix_ridecheck_worker_created", "ridecheck_events", ["worker_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ridecheck_worker_created", table_name="ridecheck_events")
    op.drop_index("ix_ridecheck_task_status", table_name="ridecheck_events")
    op.drop_index(op.f("ix_ridecheck_events_created_at"), table_name="ridecheck_events")
    op.drop_table("ridecheck_events")

    op.drop_index("ix_affinity_worker_type", table_name="customer_worker_affinities")
    op.drop_index(op.f("ix_customer_worker_affinities_created_at"), table_name="customer_worker_affinities")
    op.drop_table("customer_worker_affinities")

    op.drop_index("ix_payout_requests_worker_created", table_name="payout_requests")
    op.drop_index(op.f("ix_payout_requests_status"), table_name="payout_requests")
    op.drop_index(op.f("ix_payout_requests_created_at"), table_name="payout_requests")
    op.drop_table("payout_requests")

    op.drop_index(op.f("ix_worker_quest_progress_quest_id"), table_name="worker_quest_progress")
    op.drop_index(op.f("ix_worker_quest_progress_created_at"), table_name="worker_quest_progress")
    op.drop_table("worker_quest_progress")

    op.drop_index("ix_worker_quests_active_date", table_name="worker_quests")
    op.drop_index(op.f("ix_worker_quests_created_at"), table_name="worker_quests")
    op.drop_table("worker_quests")

    op.drop_index("ix_task_bids_worker", table_name="task_bids")
    op.drop_index("ix_task_bids_task_status", table_name="task_bids")
    op.drop_index(op.f("ix_task_bids_status"), table_name="task_bids")
    op.drop_index(op.f("ix_task_bids_created_at"), table_name="task_bids")
    op.drop_table("task_bids")

    op.drop_constraint("fk_worker_profiles_queued_task_id_tasks", "worker_profiles", type_="foreignkey")
    op.drop_column("worker_profiles", "last_online_at")
    op.drop_column("worker_profiles", "upi_id")
    op.drop_column("worker_profiles", "wrapping_up_soon")
    op.drop_column("worker_profiles", "queued_task_id")
    op.drop_column("worker_profiles", "commission_rate")
    op.drop_column("worker_profiles", "tier")

    op.drop_index(op.f("ix_tasks_scheduled_for"), table_name="tasks")
    op.drop_column("tasks", "bids_close_at")
    op.drop_column("tasks", "return_otp_verified_at")
    op.drop_column("tasks", "return_otp_locked_at")
    op.drop_column("tasks", "return_otp_attempts")
    op.drop_column("tasks", "return_otp_display")
    op.drop_column("tasks", "return_otp_hash")
    op.drop_column("tasks", "is_round_trip")
    op.drop_column("tasks", "worker_confirmed_readiness")
    op.drop_column("tasks", "scheduled_for")
    op.drop_column("tasks", "is_scheduled")
    op.drop_column("tasks", "tip_amount")
