import datetime
import json

from CTFd.models import Challenges, db

TEAM_CODE_TOKEN = "{team}"
TEAM_CODE_LENGTH = 12
# A realistic team code (lowercase hex, like real ones) for the test run of generate.py on save.
TEST_TEAM_CODE = "0123456789ab"
DELIVERY_MODES = ("flag", "replace", "script", "variants")


class PersonalChallenge(Challenges):
    """A challenge whose flag differs per account (team in teams mode, user in users mode)."""

    __tablename__ = "flagprint_challenges"
    __mapper_args__ = {"polymorphic_identity": "classic"}
    id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True)
    # e.g. "flag{st3g0_l0v3s_y0u_{team}}"; {team} becomes the account's 12-hex code
    flag_template = db.Column("personal_flag_template", db.String(255), nullable=False, default="")
    # flag: flag only (service challenges) | replace: swap the sample flag inside the uploaded file
    # script: run the author's generate.py per account | variants: fixed answers, one variant per account
    delivery = db.Column("personal_delivery", db.String(16), nullable=False, default="flag")
    filename = db.Column("personal_filename", db.String(255))
    variants_json = db.Column("personal_variants", db.Text)

    @property
    def sample_flag(self):
        return (self.flag_template or "").replace(TEAM_CODE_TOKEN, "X" * TEAM_CODE_LENGTH)

    @property
    def variants(self):
        try:
            value = json.loads(self.variants_json or "[]")
        except ValueError:
            return []
        return [v for v in value if isinstance(v, dict) and str(v.get("answer", "")).strip()]


class ShareEvent(db.Model):
    """A submission of a flag (or variant answer) that was issued to a different account."""

    __tablename__ = "flagprint_events"
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    submitter_account_id = db.Column(db.Integer, nullable=False, index=True)
    owner_account_id = db.Column(db.Integer, index=True)
    variant = db.Column(db.Integer)
    provided = db.Column(db.Text, nullable=False)
    ip = db.Column(db.String(46))
    date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    challenge = db.relationship("Challenges", foreign_keys=[challenge_id], lazy="joined")
    user = db.relationship("Users", foreign_keys=[user_id], lazy="joined")


class ShameEntry(db.Model):
    """A Hall of Shame listing: added automatically from a share event, or by an admin."""

    __tablename__ = "flagprint_shame"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="SET NULL"))
    reason = db.Column(db.String(300), nullable=False)
    source = db.Column(db.String(16), nullable=False, default="manual")  # auto | manual
    visible = db.Column(db.Boolean, nullable=False, default=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)


class FlagRotation(db.Model):
    """How many times an account's flag for a challenge has been regenerated (0 = never)."""

    __tablename__ = "flagprint_rotations"
    __table_args__ = (db.UniqueConstraint("challenge_id", "account_id", name="uq_flagprint_rotation"),)
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = db.Column(db.Integer, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=0)
    date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
