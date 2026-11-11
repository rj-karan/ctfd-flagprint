"""Flagprint: per-team flags and files for CTFd, shared-flag detection and an admin monitor."""
import json
import os

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from sqlalchemy import func

from CTFd.models import Challenges, Solves, Submissions, Tracking, Users, db
from CTFd.exceptions.challenges import ChallengeCreateException, ChallengeUpdateException
from CTFd.plugins import (
    Menu,
    register_admin_plugin_menu_bar,
    register_admin_plugin_script,
)
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge, calculate_value
from CTFd.plugins.challenges.decay import DECAY_FUNCTIONS
from CTFd.plugins.migrations import upgrade
from CTFd.utils import get_config, set_config
from CTFd.utils.config import is_teams_mode
from CTFd.utils.dates import ctf_ended, ctf_paused, ctf_started
from CTFd.utils.decorators import admins_only, authed_only, require_verified_emails
from CTFd.utils.modes import get_model
from CTFd.utils.user import get_ip, is_admin

from . import files
from .flags import (
    _secret,
    regenerate,
    versions,
    classify,
    current_account_id,
    flag_for,
    identify_flag,
    variant_index,
)
from .models import DELIVERY_MODES, TEAM_CODE_TOKEN, TEST_TEAM_CODE, PersonalChallenge, ShameEntry, ShareEvent

# Players can see asset paths in the challenge API, so every path follows the folder the plugin is installed in.
# Install it under a neutral name (e.g. CTFd/plugins/classic) and nothing player-facing mentions Flagprint.
PLUGIN_DIR = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
ASSETS = f"/plugins/{PLUGIN_DIR}/assets/"

SHAME_ENABLED_KEY = "flagprint_shame_enabled"  # public Hall of Shame page on/off (default off)
SHAME_AUTO_KEY = "flagprint_shame_auto"  # add caught teams automatically (default on)
SHAME_ROUTE = "hall-of-shame"  # menu routes are page paths, without the leading slash


def shame_enabled():
    return bool(get_config(SHAME_ENABLED_KEY, default=False))


def shame_auto():
    return bool(get_config(SHAME_AUTO_KEY, default=True))


# Other plugins with per-team flags (the container instancer) register a callable here that returns
# their per-team challenges, so the monitor, flag lookup and share logging cover them too.
PER_TEAM_SOURCES = []
# Hooks for the Team flags section. TEAM_FLAG_EXTRAS: (challenge, account_ids) -> {account_id: {extra fields}}.
# ON_REGENERATE: (challenge, account_ids) -> None, e.g. stop instances still holding the old flag.
TEAM_FLAG_EXTRAS = []
ON_REGENERATE = []


def per_team_challenges():
    challenges = PersonalChallenge.query.all()
    for source in PER_TEAM_SOURCES:
        challenges.extend(source())
    return sorted(challenges, key=lambda c: (c.category or "", c.name or ""))


def record_if_shared(user, team, challenge, request):
    """After a wrong submission: if it is another account's flag, log it and add a Hall of Shame entry."""
    data = request.form or request.get_json()
    submission = data["submission"].strip()
    account_id = team.id if (is_teams_mode() and team) else user.id
    verdict = classify(challenge, submission, account_id)
    if verdict.status != "shared":
        return
    db.session.add(
        ShareEvent(
            challenge_id=challenge.id,
            user_id=user.id,
            submitter_account_id=account_id,
            owner_account_id=verdict.owner_account_id,
            variant=verdict.variant,
            provided=submission,
            ip=get_ip(req=request),
        )
    )
    # One automatic Hall of Shame entry per team and challenge, however many times they retry.
    if shame_auto() and not ShameEntry.query.filter_by(
        account_id=account_id, challenge_id=challenge.id, source="auto"
    ).first():
        db.session.add(
            ShameEntry(
                account_id=account_id,
                challenge_id=challenge.id,
                reason=f"Got caught on {challenge.name}",
                source="auto",
            )
        )
    db.session.commit()


class PersonalValueChallenge(BaseChallenge):
    # Players can see the type id and name in the API, so both stay neutral.
    id = "classic"
    name = "classic"
    templates = {
        "create": ASSETS + "create.html",
        "update": ASSETS + "update.html",
        "view": ASSETS + "view.html",
    }
    scripts = {
        "create": ASSETS + "form.js",
        "update": ASSETS + "form.js",
        # The standard challenge's script (ours was an identical copy), so nothing player-facing names this plugin.
        "view": "/plugins/challenges/assets/view.js",
    }
    route = ASSETS
    challenge_model = PersonalChallenge

    # Form fields that are not model columns: files travel inside the JSON as base64.
    EXTRA_FIELDS = ("upload_source", "upload_script", "upload_input", "remove_input", "output_name")

    @classmethod
    def _prepare(cls, data, challenge=None):
        """Check the whole form before anything is written.

        Returns (model fields, plan); the plan says which files to write once the row exists.
        Raises GenerationError with a message for the admin if anything is wrong."""
        data = {k: v for k, v in dict(data).items() if k != "flags"}
        extras = {k: data.pop(k, None) for k in cls.EXTRA_FIELDS}

        def current(key, default=None):
            if key in data:
                return data[key]
            return getattr(challenge, key, default) if challenge is not None else default

        delivery = current("delivery", "flag")
        template = (current("flag_template", "") or "").strip()
        if delivery not in DELIVERY_MODES:
            raise files.GenerationError("Choose how teams get their flag.")
        if delivery != "variants" and template.count(TEAM_CODE_TOKEN) != 1:
            raise files.GenerationError("The flag template must contain {team} exactly once, e.g. flag{my_flag_{team}}.")
        if "flag_template" in data:
            data["flag_template"] = template
        sample = template.replace(TEAM_CODE_TOKEN, "X" * 12)
        plan = {}

        if delivery == "replace":
            upload = files.decode_upload(extras["upload_source"])
            if upload:
                name, content = upload
            elif challenge is not None and challenge.delivery == "replace" and challenge.filename:
                name, content = challenge.filename, files.read_bytes(files.source_path(challenge))
            else:
                name, content = None, None
            if content is None:
                raise files.GenerationError("Upload the file that contains the sample flag.")
            found = files.count_sample(content, sample)
            if not found:
                raise files.GenerationError(
                    f"The file {name} does not contain the sample flag {sample}. Put exactly that text in the file "
                    "(not compressed or encrypted) so each team's copy can get their own flag."
                )
            data["filename"] = files.safe_name(name)
            if upload:
                plan["source"] = (data["filename"], content)

        elif delivery == "script":
            script = files.decode_upload(extras["upload_script"])
            script_bytes = script[1] if script else (
                files.read_bytes(files.script_path(challenge.id)) if challenge is not None else None)
            if script_bytes is None:
                raise files.GenerationError("Upload generate.py.")
            output = files.safe_name(extras["output_name"] or (challenge.filename if challenge is not None and challenge.delivery == "script" else ""))
            if not output:
                raise files.GenerationError("Enter the download name players get, e.g. image.png.")
            data["filename"] = output
            item = files.decode_upload(extras["upload_input"])
            if item:
                item = (files.safe_name(item[0]), item[1])
            elif challenge is not None and not extras["remove_input"]:
                found = files.input_file(challenge.id)
                item = (found[0], files.read_bytes(found[1])) if found else None
            changed = bool(script or extras["upload_input"] or extras["remove_input"]) or challenge is None or (
                output != challenge.filename or template != challenge.flag_template or challenge.delivery != "script")
            if changed:
                # Prove the script works before saving it: one run with a realistic team flag.
                files.run_script(script_bytes, output, template.replace(TEAM_CODE_TOKEN, TEST_TEAM_CODE), item)
            if script:
                plan["script"] = script_bytes
            if extras["upload_input"]:
                plan["input"] = item
            elif extras["remove_input"]:
                plan["remove_input"] = True

        elif delivery == "variants":
            raw = current("variants_json", "[]") or "[]"
            try:
                rows = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                raise files.GenerationError("The variants could not be read. Reload the page and try again.")
            rows = [
                {"description": str(r.get("description", "")).strip(), "answer": str(r.get("answer", "")).strip()}
                for r in rows if isinstance(r, dict) and str(r.get("answer", "")).strip()
            ]
            if len(rows) < 2:
                raise files.GenerationError("Add at least two variants, each with an answer.")
            answers = [" ".join(r["answer"].split()).casefold() for r in rows]
            if len(set(answers)) != len(answers):
                raise files.GenerationError("Two variants have the same answer. Every answer must be different.")
            data["variants_json"] = json.dumps(rows)
            data["flag_template"] = template

        return data, plan

    @staticmethod
    def _write(challenge_id, plan):
        if "source" in plan:
            files.save_source_bytes(challenge_id, *plan["source"])
        if "script" in plan:
            files.save_script_bytes(challenge_id, plan["script"])
        if "input" in plan:
            files.save_input_bytes(challenge_id, *plan["input"])
        if plan.get("remove_input"):
            files.remove_input(challenge_id)
        files.clear_issued(challenge_id)

    @classmethod
    def create(cls, request):
        try:
            data, plan = cls._prepare(request.form or request.get_json() or {})
        except files.GenerationError as error:
            raise ChallengeCreateException(str(error))
        challenge = cls.challenge_model(**data)
        db.session.add(challenge)
        db.session.commit()
        # After a CTFd reset, ids start again at 1: never serve a file left over from an older challenge.
        files.delete_all(challenge.id)
        try:
            cls._write(challenge.id, plan)
        except (files.GenerationError, OSError) as error:
            files.delete_all(challenge.id)
            db.session.delete(challenge)
            db.session.commit()
            raise ChallengeCreateException(f"Could not save the challenge's files: {error}")
        return challenge

    @classmethod
    def read(cls, challenge):
        challenge = PersonalChallenge.query.filter_by(id=challenge.id).first()
        data = super().read(challenge)
        # CTFd also sends this to players with the challenge, so the per-team settings are for admins only.
        if is_admin():
            data.update(
                {
                    "flag_template": challenge.flag_template,
                    "delivery": challenge.delivery,
                    "filename": challenge.filename,
                }
            )
        return data

    @classmethod
    def update(cls, challenge, request):
        try:
            data, plan = cls._prepare(request.form or request.get_json() or {}, challenge)
            cls._write(challenge.id, plan)
        except files.GenerationError as error:
            raise ChallengeUpdateException(str(error))
        for attr, value in data.items():
            if attr in ("id", "type"):
                continue
            if attr in ("initial", "minimum", "decay") and value not in (None, ""):
                value = float(value)
            setattr(challenge, attr, value)
        db.session.commit()
        files.clear_issued(challenge.id)
        if challenge.function in DECAY_FUNCTIONS:
            return calculate_value(challenge)
        return challenge

    @classmethod
    def delete(cls, challenge):
        ShareEvent.query.filter_by(challenge_id=challenge.id).delete()
        files.delete_all(challenge.id)
        super().delete(challenge)

    @classmethod
    def attempt(cls, challenge, request):
        data = request.form or request.get_json()
        verdict = classify(challenge, data["submission"], current_account_id())
        if verdict.status == "correct":
            return True, "Correct"
        # A shared flag looks like any wrong answer to the player; fail() logs it for the organizers.
        return False, "Incorrect"

    @classmethod
    def fail(cls, user, team, challenge, request):
        super().fail(user, team, challenge, request)
        record_if_shared(user, team, challenge, request)


def view_context(challenge):
    """What the challenge popup shows the current player: their own file link or variant text."""
    personal = PersonalChallenge.query.filter_by(id=challenge.id).first()
    account_id = current_account_id()
    context = {"description": None, "download": None, "preview": account_id is None}
    if personal is None or account_id is None:
        return context
    if personal.delivery == "variants":
        index = variant_index(personal, account_id)
        if index is not None:
            # Imported here, like CTFd's own models do: these helpers need an application context at import time.
            from CTFd.utils.config.pages import build_markdown
            from CTFd.utils.helpers import markup

            context["description"] = markup(build_markdown(personal.variants[index].get("description", "")))
    elif personal.delivery in ("replace", "script") and personal.filename:
        context["download"] = {
            "url": url_for("flagprint.download", challenge_id=personal.id),
            "name": personal.filename,
        }
    return context


blueprint = Blueprint("flagprint", __name__, template_folder="templates")


def _locked(challenge, account_id):
    """True while this account still has to solve one of the challenge's prerequisites."""
    prerequisites = set((challenge.requirements or {}).get("prerequisites", []))
    if not prerequisites:
        return False
    column = Solves.team_id if is_teams_mode() else Solves.user_id
    solved = {row[0] for row in Solves.query.with_entities(Solves.challenge_id).filter(column == account_id).all()}
    return not prerequisites <= solved


def _account_label(account_id):
    if account_id is None:
        return "—"
    labels = g.setdefault("flagprint_labels", {})  # one lookup per account per request, not per table row
    if account_id not in labels:
        account = get_model().query.filter_by(id=account_id).first()
        labels[account_id] = account.name if account else f"#{account_id}"
    return labels[account_id]


@blueprint.route("/download/<int:challenge_id>")
@authed_only
@require_verified_emails
def download(challenge_id):
    challenge = PersonalChallenge.query.filter_by(id=challenge_id).first_or_404()
    if challenge.delivery not in ("replace", "script") or not challenge.filename:
        abort(404)
    account_id = current_account_id()
    if account_id is None:
        abort(403)
    if not is_admin():
        if challenge.state == "hidden" or not ctf_started() or ctf_paused() or ctf_ended():
            abort(403)
        if _locked(challenge, account_id):
            abort(403)  # the same rule CTFd applies to the challenge itself: prerequisites first
    try:
        path = files.issued_file(challenge, account_id, flag_for(challenge, account_id))
    except files.GenerationError as error:
        if is_admin():
            return str(error), 500
        abort(500)
    return send_file(path, as_attachment=True, download_name=challenge.filename, max_age=0)


@blueprint.route("/admin/flagprint")
@admins_only
def monitor():
    section = request.args.get("section", "alerts")
    challenge_id = request.args.get("challenge_id", type=int)
    personal = PersonalChallenge.query.order_by(PersonalChallenge.category, PersonalChallenge.name).all()
    per_team = per_team_challenges()

    alerts = ShareEvent.query.order_by(ShareEvent.date.desc())
    if challenge_id:
        alerts = alerts.filter_by(challenge_id=challenge_id)
    alerts = alerts.limit(500).all()

    submissions = []
    if section == "submissions":
        query = Submissions.query.filter(Submissions.challenge_id.in_([c.id for c in per_team] or [-1]))
        if challenge_id:
            query = query.filter_by(challenge_id=challenge_id)
        for submission in query.order_by(Submissions.date.desc()).limit(500).all():
            challenge = next(c for c in per_team if c.id == submission.challenge_id)
            match = identify_flag(challenge, submission.provided)
            submissions.append({"row": submission, "challenge": challenge, "match": match})

    shared_ips = []
    if section == "ips":
        account_column = Users.team_id if is_teams_mode() else Users.id
        rows = (
            db.session.query(Tracking.ip, func.count(func.distinct(account_column)))
            .join(Users, Users.id == Tracking.user_id)
            .filter(account_column.isnot(None))
            .group_by(Tracking.ip)
            .having(func.count(func.distinct(account_column)) > 1)
            .all()
        )
        for ip, count in rows:
            accounts = (
                db.session.query(account_column)
                .join(Tracking, Tracking.user_id == Users.id)
                .filter(Tracking.ip == ip, account_column.isnot(None))
                .distinct()
                .all()
            )
            shared_ips.append({"ip": ip, "count": count, "accounts": [_account_label(a[0]) for a in accounts]})

    shame = []
    accounts = []
    if section == "shame":
        shame = ShameEntry.query.order_by(ShameEntry.date.desc()).all()
        accounts = get_model().query.order_by(get_model().name).limit(1000).all()

    lookup = None
    if section == "lookup" and request.args.get("flag"):
        lookup_challenge = next((c for c in per_team if c.id == challenge_id), None) if challenge_id else None
        candidates = [lookup_challenge] if lookup_challenge else per_team
        for challenge in candidates:
            match = identify_flag(challenge, request.args["flag"])
            if match:
                lookup = {"challenge": challenge, "match": match}
                break
        if lookup is None:
            lookup = {"challenge": None, "match": None}

    return render_template(
        "flagprint_monitor.html",
        section=section,
        personal=personal,
        per_team=per_team,
        challenge_id=challenge_id,
        alerts=alerts,
        submissions=submissions,
        shared_ips=shared_ips,
        lookup=lookup,
        shame=shame,
        accounts=accounts,
        shame_enabled=shame_enabled(),
        shame_auto=shame_auto(),
        account_label=_account_label,
        teams_mode=is_teams_mode(),
        account_url=lambda account_id: url_for(
            "admin.teams_detail" if is_teams_mode() else "admin.users_detail",
            **({"team_id": account_id} if is_teams_mode() else {"user_id": account_id}),
        ),
    )


@blueprint.route("/admin/flagprint/shame", methods=["POST"])
@admins_only
def shame_admin():
    action = request.form.get("action")
    if action == "settings":
        set_config(SHAME_ENABLED_KEY, "true" if request.form.get("enabled") == "on" else "false")
        set_config(SHAME_AUTO_KEY, "true" if request.form.get("auto") == "on" else "false")
        flash("Hall of Shame settings saved.", "success")
    elif action == "add":
        account_id = request.form.get("account_id", type=int)
        reason = request.form.get("reason", "").strip()[:300]
        if account_id is None or get_model().query.filter_by(id=account_id).first() is None or not reason:
            flash("Choose a team and write a reason.", "danger")
        else:
            db.session.add(ShameEntry(account_id=account_id, reason=reason, source="manual"))
            db.session.commit()
            flash("Added to the Hall of Shame.", "success")
    elif action in ("toggle", "delete"):
        entry = ShameEntry.query.filter_by(id=request.form.get("entry_id", type=int)).first_or_404()
        if action == "toggle":
            entry.visible = not entry.visible
        else:
            db.session.delete(entry)
        db.session.commit()
    else:
        abort(400)
    return redirect(url_for("flagprint.monitor", section="shame"))


@blueprint.route("/admin/flagprint/alerts.json")
@admins_only
def alerts_feed():
    """Shared-flag events newer than ?after=<id>, polled by alerts.js on every admin page."""
    after = request.args.get("after", type=int)
    latest = db.session.query(func.max(ShareEvent.id)).scalar() or 0
    if after is None:
        return {"latest": latest, "events": []}
    events = ShareEvent.query.filter(ShareEvent.id > after).order_by(ShareEvent.id).limit(20).all()
    return {
        "latest": latest,
        "events": [
            {
                "id": e.id,
                "submitter": _account_label(e.submitter_account_id),
                "owner": _account_label(e.owner_account_id) if e.owner_account_id else f"variant #{(e.variant or 0) + 1}",
                "challenge": e.challenge.name if e.challenge else "?",
            }
            for e in events
        ],
    }


@blueprint.route("/" + SHAME_ROUTE)
def hall_of_shame():
    if not shame_enabled() and not is_admin():
        abort(404)
    entries = ShameEntry.query.filter_by(visible=True).order_by(ShameEntry.date.desc()).all()
    return render_template(
        "flagprint_hall_of_shame.html",
        entries=entries,
        account_label=_account_label,
        preview=not shame_enabled(),
    )


@blueprint.route("/admin/flagprint/challenge/<int:challenge_id>", methods=["GET", "POST"])
@admins_only
def challenge_settings(challenge_id):
    """Old separate settings page: everything now lives on the challenge's own edit page."""
    return redirect(url_for("admin.challenges_detail", challenge_id=challenge_id))


@blueprint.route("/admin/flagprint/challenge/<int:challenge_id>/preview")
@admins_only
def challenge_preview(challenge_id):
    """Download the file a given team or user gets, generating it if needed."""
    challenge = PersonalChallenge.query.filter_by(id=challenge_id).first_or_404()
    account_id = request.args.get("account_id", type=int)
    if account_id is None or challenge.delivery not in ("replace", "script"):
        abort(404)
    try:
        path = files.issued_file(challenge, account_id, flag_for(challenge, account_id))
    except files.GenerationError as error:
        return str(error), 500
    return send_file(path, as_attachment=True, download_name=f"preview-{account_id}-{challenge.filename}", max_age=0)


def _per_team_challenge(challenge_id):
    return next((c for c in per_team_challenges() if c.id == challenge_id), None)


def _account_admin_url(account_id):
    if is_teams_mode():
        return url_for("admin.teams_detail", team_id=account_id)
    return url_for("admin.users_detail", user_id=account_id)


@blueprint.route("/admin/flagprint/flags/<int:challenge_id>")
@admins_only
def team_flags(challenge_id):
    """Every team's flag for one per-team challenge, with solve, sharing, file and instance status."""
    challenge = _per_team_challenge(challenge_id)
    if challenge is None:
        return {"success": False, "error": "This challenge does not use per-team flags."}, 404
    model = get_model()
    accounts = model.query.order_by(model.name).all()
    ids = [a.id for a in accounts]
    current = versions(challenge.id)

    solves, fails = {}, {}
    for submission in Submissions.query.filter_by(challenge_id=challenge.id).all():
        account_id = submission.team_id if is_teams_mode() else submission.user_id
        if submission.type == "correct":
            solves[account_id] = submission.date
        elif submission.type == "incorrect":
            fails[account_id] = fails.get(account_id, 0) + 1
    leaked = dict(
        db.session.query(ShareEvent.owner_account_id, func.count(ShareEvent.id))
        .filter(ShareEvent.challenge_id == challenge.id).group_by(ShareEvent.owner_account_id).all()
    )
    copied = dict(
        db.session.query(ShareEvent.submitter_account_id, func.count(ShareEvent.id))
        .filter(ShareEvent.challenge_id == challenge.id).group_by(ShareEvent.submitter_account_id).all()
    )
    extras = {}
    for hook in TEAM_FLAG_EXTRAS:
        for account_id, fields in (hook(challenge, ids) or {}).items():
            extras.setdefault(account_id, {}).update(fields)

    variants_mode = challenge.delivery == "variants"
    has_file = challenge.type == "classic" and challenge.delivery in ("replace", "script") and challenge.filename
    rows = []
    for account in accounts:
        version = current.get(account.id, 0)
        if variants_mode:
            index = variant_index(challenge, account.id, version)
            flag = f"#{index + 1}: {challenge.variants[index]['answer']}" if index is not None else None
        else:
            flag = flag_for(challenge, account.id, version)
        row = {
            "id": account.id,
            "name": account.name,
            "url": _account_admin_url(account.id),
            "hidden": bool(getattr(account, "hidden", False)),
            "banned": bool(getattr(account, "banned", False)),
            "flag": flag,
            "version": version,
            "solved": solves[account.id].isoformat() + "Z" if account.id in solves else None,
            "fails": fails.get(account.id, 0),
            "leaked": leaked.get(account.id, 0),
            "copied": copied.get(account.id, 0),
            "file": url_for("flagprint.challenge_preview", challenge_id=challenge.id, account_id=account.id) if has_file else None,
        }
        row.update(extras.get(account.id, {}))
        rows.append(row)

    return {
        "success": True,
        "challenge": {
            "id": challenge.id,
            "name": challenge.name,
            "type": challenge.type,
            "mode": "variants" if variants_mode else ("instance" if challenge.type == "container" else challenge.delivery),
            "template": challenge.flag_template,
            "file": challenge.filename if has_file else None,
        },
        "teams_mode": is_teams_mode(),
        "rows": rows,
    }


def reset_progress(challenge, account_ids):
    """As if the challenge were newly deployed for these accounts: remove their solve and every
    attempt, so the points leave the scoreboard and attempt limits start over.
    Share alerts and Hall of Shame entries are kept: they are the record of what happened."""
    from CTFd.cache import cache, clear_challenges, clear_standings

    column = Submissions.team_id if is_teams_mode() else Submissions.user_id
    submissions = Submissions.query.filter(
        Submissions.challenge_id == challenge.id, column.in_(account_ids or [-1])
    ).all()
    solves = sum(1 for s in submissions if s.type == "correct")
    for submission in submissions:  # one by one, like CTFd's own delete, so solve/fail rows go too
        db.session.delete(submission)
    db.session.commit()
    for account_id in account_ids:
        cache.expire(f"account_kpm_{account_id}_{challenge.id}", 0)
    if solves and challenge.function in DECAY_FUNCTIONS:
        calculate_value(challenge)  # dynamic points go back up
    clear_standings()
    clear_challenges()
    return {"solves": solves, "attempts": len(submissions) - solves}


@blueprint.route("/admin/flagprint/flags/<int:challenge_id>/regenerate", methods=["POST"])
@admins_only
def team_flags_regenerate(challenge_id):
    challenge = _per_team_challenge(challenge_id)
    if challenge is None:
        return {"success": False, "error": "This challenge does not use per-team flags."}, 404
    body = request.get_json(silent=True) or {}
    known = {a.id for a in get_model().query.with_entities(get_model().id).all()}
    if body.get("all"):
        account_ids = sorted(known)
    else:
        try:
            account_ids = [int(body.get("account_id"))]
        except (TypeError, ValueError):
            return {"success": False, "error": "Choose a team."}, 400
        if account_ids[0] not in known:
            return {"success": False, "error": "That team no longer exists."}, 404
    regenerate(challenge.id, account_ids)
    removed = reset_progress(challenge, account_ids)
    if challenge.type == "classic":
        for account_id in account_ids:
            files.clear_account(challenge.id, account_id)
    for hook in ON_REGENERATE:
        hook(challenge, account_ids)
    return {"success": True, "count": len(account_ids), "removed": removed}


def form_state(challenge):
    """What the edit form shows about a challenge's stored files."""
    if challenge is None:
        return {}
    found = files.input_file(challenge.id)
    return {
        "source": challenge.filename if challenge.delivery == "replace" and challenge.filename else None,
        "occurrences": files.sample_occurrences(challenge) if challenge.delivery == "replace" else 0,
        "has_script": os.path.exists(files.script_path(challenge.id)),
        "input": found[0] if found else None,
    }


def load(app):
    upgrade(plugin_name=PLUGIN_DIR)
    _secret()  # settle the flag secret before any worker issues a flag
    CHALLENGE_CLASSES[PersonalValueChallenge.id] = PersonalValueChallenge
    # Create/update forms explain how the flags work, so only admins may fetch them
    # (CTFd's register_plugin_assets_directory ignores its admins_only flag).
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    app.add_url_rule(
        ASSETS + "<path:path>",
        endpoint=f"plugins.{PLUGIN_DIR}.assets",
        view_func=admins_only(lambda path: send_from_directory(assets_dir, path)),
    )
    register_admin_plugin_script(ASSETS + "alerts.js")
    register_admin_plugin_script(ASSETS + "team_flags.js")
    app.register_blueprint(blueprint)
    app.jinja_env.globals.update(
        flagprint_view=view_context, flagprint_shame_enabled=shame_enabled, flagprint_form_state=form_state,
        flagprint_assets=ASSETS.lstrip("/"),
    )
    register_admin_plugin_menu_bar("Flagprint", "/admin/flagprint")

    @app.before_request
    def sync_shame_link():
        # The Hall of Shame can be switched on and off at runtime, so every worker keeps its menu in step with the setting.
        listed = [m for m in app.plugin_menu_bar if m.route == SHAME_ROUTE]
        if shame_enabled() and not listed:
            app.plugin_menu_bar.append(Menu(title="Hall of Shame", route=SHAME_ROUTE, link_target=None))
        elif listed and not shame_enabled():
            for item in listed:
                app.plugin_menu_bar.remove(item)
