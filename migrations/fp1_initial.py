"""Flagprint tables: per-team challenges, shared-flag events, Hall of Shame entries and flag rotations."""
import sqlalchemy as sa

from CTFd.plugins.migrations import get_all_tables

revision = "fp1_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(op=None):
    tables = get_all_tables(op)
    if "flagprint_challenges" not in tables:
        op.create_table(
            "flagprint_challenges",
            sa.Column("id", sa.Integer, sa.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("personal_flag_template", sa.String(255), nullable=False),
            sa.Column("personal_delivery", sa.String(16), nullable=False),
            sa.Column("personal_filename", sa.String(255)),
            sa.Column("personal_variants", sa.Text),
        )
    if "flagprint_events" not in tables:
        op.create_table(
            "flagprint_events",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("challenge_id", sa.Integer, sa.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("submitter_account_id", sa.Integer, nullable=False),
            sa.Column("owner_account_id", sa.Integer),
            sa.Column("variant", sa.Integer),
            sa.Column("provided", sa.Text, nullable=False),
            sa.Column("ip", sa.String(46)),
            sa.Column("date", sa.DateTime, nullable=False),
        )
        op.create_index("ix_flagprint_events_challenge_id", "flagprint_events", ["challenge_id"])
        op.create_index("ix_flagprint_events_submitter_account_id", "flagprint_events", ["submitter_account_id"])
        op.create_index("ix_flagprint_events_owner_account_id", "flagprint_events", ["owner_account_id"])
        op.create_index("ix_flagprint_events_date", "flagprint_events", ["date"])
    if "flagprint_shame" not in tables:
        op.create_table(
            "flagprint_shame",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("account_id", sa.Integer, nullable=False),
            sa.Column("challenge_id", sa.Integer, sa.ForeignKey("challenges.id", ondelete="SET NULL")),
            sa.Column("reason", sa.String(300), nullable=False),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("visible", sa.Boolean, nullable=False),
            sa.Column("date", sa.DateTime, nullable=False),
        )
        op.create_index("ix_flagprint_shame_account_id", "flagprint_shame", ["account_id"])
        op.create_index("ix_flagprint_shame_date", "flagprint_shame", ["date"])
    if "flagprint_rotations" not in tables:
        op.create_table(
            "flagprint_rotations",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("challenge_id", sa.Integer, sa.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", sa.Integer, nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("date", sa.DateTime, nullable=False),
            sa.UniqueConstraint("challenge_id", "account_id", name="uq_flagprint_rotation"),
        )
        op.create_index("ix_flagprint_rotations_challenge_id", "flagprint_rotations", ["challenge_id"])


def downgrade(op=None):
    op.drop_table("flagprint_rotations")
    op.drop_table("flagprint_shame")
    op.drop_table("flagprint_events")
    op.drop_table("flagprint_challenges")
