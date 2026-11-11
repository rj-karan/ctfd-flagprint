"""Per-account flag issuing and classification of submissions."""
import datetime
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from CTFd.utils import get_config, set_config
from CTFd.utils.config import is_teams_mode
from CTFd.utils.modes import get_model
from CTFd.utils.user import get_current_team, get_current_user

from .models import TEAM_CODE_LENGTH, TEAM_CODE_TOKEN, FlagRotation

SECRET_CONFIG_KEY = "flagprint_secret"


def _secret():
    # Kept in the database rather than derived from SECRET_KEY so rotating the session key never changes issued flags.
    value = get_config(SECRET_CONFIG_KEY)
    if not value:
        value = secrets.token_hex(32)
        set_config(SECRET_CONFIG_KEY, value)
    return value.encode()


def versions(challenge_id):
    """{account_id: version} for accounts whose flag on this challenge was regenerated."""
    rows = FlagRotation.query.filter_by(challenge_id=challenge_id).all()
    return {row.account_id: row.version for row in rows}


def version_of(challenge_id, account_id):
    row = FlagRotation.query.filter_by(challenge_id=challenge_id, account_id=account_id).first()
    return row.version if row else 0


def team_code(challenge_id, account_id, version=None):
    if version is None:
        version = version_of(challenge_id, account_id)
    # Version 0 keeps the original message, so flags issued before regeneration existed stay valid.
    message = f"{challenge_id}:{account_id}" if not version else f"{challenge_id}:{account_id}:v{version}"
    return hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()[:TEAM_CODE_LENGTH]


def flag_for(challenge, account_id, version=None):
    return challenge.flag_template.replace(TEAM_CODE_TOKEN, team_code(challenge.id, account_id, version))


def variant_index(challenge, account_id, version=None):
    count = len(challenge.variants)
    if not count:
        return None
    return int(team_code(challenge.id, account_id, version), 16) % count


def regenerate(challenge_id, account_ids):
    """Give each account a new flag for this challenge. Their old flags stop working."""
    from CTFd.models import db

    for account_id in account_ids:
        row = FlagRotation.query.filter_by(challenge_id=challenge_id, account_id=account_id).first()
        if row is None:
            db.session.add(FlagRotation(challenge_id=challenge_id, account_id=account_id, version=1))
        else:
            row.version += 1
            row.date = datetime.datetime.utcnow()
    db.session.commit()


def current_account_id():
    if is_teams_mode():
        team = get_current_team()
        return team.id if team else None
    user = get_current_user()
    return user.id if user else None


def all_account_ids():
    model = get_model()
    return [row.id for row in model.query.with_entities(model.id).all()]


def _template_pattern(challenge):
    escaped = re.escape(challenge.flag_template)
    return re.compile(escaped.replace(re.escape(TEAM_CODE_TOKEN), f"([0-9a-f]{{{TEAM_CODE_LENGTH}}})"))


def owner_of_code(challenge, code):
    """(account_id, retired) for a code: whose it is, and whether it was replaced by regeneration."""
    current = versions(challenge.id)
    for account_id in all_account_ids():
        latest = current.get(account_id, 0)
        for version in range(latest, -1, -1):
            if hmac.compare_digest(team_code(challenge.id, account_id, version), code):
                return account_id, version != latest
    return None, False


def _normalise_answer(value):
    return " ".join(str(value).split()).casefold()


@dataclass
class Verdict:
    status: str  # "correct" | "shared" | "wrong"
    owner_account_id: int = None
    variant: int = None
    retired: bool = False


def classify(challenge, submission, account_id):
    """Decide whether a submission is this account's flag, another account's flag, or simply wrong."""
    submission = submission.strip()
    if account_id is None:
        return Verdict("wrong")

    if challenge.delivery == "variants":
        own = variant_index(challenge, account_id)
        answer = _normalise_answer(submission)
        for index, variant in enumerate(challenge.variants):
            if _normalise_answer(variant["answer"]) == answer:
                if index == own:
                    return Verdict("correct", variant=index)
                return Verdict("shared", variant=index)
        return Verdict("wrong")

    if hmac.compare_digest(submission.encode(), flag_for(challenge, account_id).encode()):
        return Verdict("correct")
    match = _template_pattern(challenge).fullmatch(submission)
    if match:
        owner, _ = owner_of_code(challenge, match.group(1))
        if owner is not None and owner != account_id:
            return Verdict("shared", owner_account_id=owner)  # a current or regenerated-away flag of another team
    return Verdict("wrong")  # includes this account's own old flag after regeneration


def identify_flag(challenge, submission):
    """Admin lookup: which account was this flag (or variant answer) issued to?"""
    submission = submission.strip()
    if challenge.delivery == "variants":
        answer = _normalise_answer(submission)
        for index, variant in enumerate(challenge.variants):
            if _normalise_answer(variant["answer"]) == answer:
                return Verdict("variant", variant=index)
        return None
    match = _template_pattern(challenge).fullmatch(submission)
    if not match:
        return None
    owner, retired = owner_of_code(challenge, match.group(1))
    return Verdict("owner", owner_account_id=owner, retired=retired) if owner is not None else None
