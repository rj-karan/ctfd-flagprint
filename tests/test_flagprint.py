import io
import zipfile

import pytest

from CTFd.models import Solves, Submissions
from CTFd.plugins.flagprint import ASSETS
from CTFd.plugins.flagprint.flags import flag_for, variant_index
from CTFd.plugins.flagprint.models import PersonalChallenge, ShareEvent
from tests.helpers import create_ctfd, destroy_ctfd, gen_team, login_as_user, register_user

TEMPLATE = "flag{r3v_m3_{team}}"


def _create(client, **extra):
    data = {
        "name": "personal",
        "category": "rev",
        "description": "find it",
        "value": 100,
        "state": "visible",
        "type": "classic",
        "flag_template": TEMPLATE,
        "delivery": "flag",
    }
    data.update(extra)
    return client.post("/api/v1/challenges", json=data)


def _attempt(client, challenge_id, submission):
    r = client.post("/api/v1/challenges/attempt", json={"challenge_id": challenge_id, "submission": submission})
    return r.get_json()["data"]


def _nonce(client):
    with client.session_transaction() as sess:
        return sess["nonce"]


def _upload(name, data):
    """A file as the challenge form sends it: JSON with base64 data."""
    import base64
    import json

    return json.dumps({"name": name, "data": base64.b64encode(data).decode()})


SAMPLE = TEMPLATE.replace("{team}", "X" * 12)


def test_flag_template_must_contain_team_code():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        r = _create(admin, flag_template="flag{static}")
        assert r.status_code == 500  # CTFd reports challenge-create errors as 500 with the message
        assert "{team}" in r.get_json()["errors"][""][0]
        assert PersonalChallenge.query.count() == 0

        challenge_id = _create(admin).get_json()["data"]["id"]
        r = admin.patch(f"/api/v1/challenges/{challenge_id}", json={"flag_template": "flag{oops}"})
        assert r.status_code != 200
        assert PersonalChallenge.query.get(challenge_id).flag_template == TEMPLATE
    destroy_ctfd(app)


def test_each_user_gets_a_different_flag_and_shared_flags_are_logged():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        challenge_id = _create(admin).get_json()["data"]["id"]
        register_user(app, name="alice", email="alice@example.com")
        register_user(app, name="bob", email="bob@example.com")
        challenge = PersonalChallenge.query.get(challenge_id)
        alice_flag, bob_flag = flag_for(challenge, 2), flag_for(challenge, 3)
        assert alice_flag != bob_flag
        assert alice_flag.startswith("flag{r3v_m3_") and len(alice_flag) == len(challenge.sample_flag)

        alice = login_as_user(app, name="alice")
        bob = login_as_user(app, name="bob")

        result = _attempt(bob, challenge_id, alice_flag)
        assert result["status"] == "incorrect"
        assert result["message"] == "Incorrect"
        event = ShareEvent.query.one()
        assert (event.submitter_account_id, event.owner_account_id, event.provided) == (3, 2, alice_flag)

        assert _attempt(bob, challenge_id, "flag{r3v_m3_000000000000}")["status"] == "incorrect"
        assert ShareEvent.query.count() == 1  # a made-up code is wrong, not shared

        # The type looks like a plain challenge; asset paths follow the install folder, so a neutral
        # folder name hides the plugin completely. Admins get the alert feed instead.
        detail = bob.get(f"/api/v1/challenges/{challenge_id}").get_json()["data"]
        assert detail["type"] == "classic" and detail["type_data"]["name"] == "classic"
        assert "flag_template" not in str(detail) and alice_flag not in str(detail)
        assert bob.get(ASSETS + "create.html").status_code != 200
        assert bob.get("/admin/flagprint/alerts.json").status_code != 200
        feed = admin.get(f"/admin/flagprint/alerts.json?after=0").get_json()
        assert [(e["submitter"], e["owner"]) for e in feed["events"]] == [("bob", "alice")]

        assert _attempt(alice, challenge_id, alice_flag)["status"] == "correct"
        assert _attempt(bob, challenge_id, bob_flag)["status"] == "correct"
        assert Solves.query.count() == 2
    destroy_ctfd(app)


def test_team_members_share_one_flag_and_other_teams_are_caught():
    app = create_ctfd(enable_plugins=True, user_mode="teams")
    with app.app_context():
        admin = login_as_user(app, name="admin")
        challenge_id = _create(admin).get_json()["data"]["id"]
        red = gen_team(app.db, name="red", email="red@example.com", member_count=2)
        blue = gen_team(app.db, name="blue", email="blue@example.com", member_count=1)
        challenge = PersonalChallenge.query.get(challenge_id)
        red_flag = flag_for(challenge, red.id)
        red_member, blue_member = red.members[1].name, blue.members[0].name
        blue_id = blue.id

        blue_client = login_as_user(app, name=blue_member)
        assert _attempt(blue_client, challenge_id, red_flag)["message"] == "Incorrect"
        event = ShareEvent.query.one()
        assert (event.submitter_account_id, event.owner_account_id) == (blue_id, red.id)

        red_client = login_as_user(app, name=red_member)
        assert _attempt(red_client, challenge_id, red_flag)["status"] == "correct"
    destroy_ctfd(app)


def test_replace_mode_issues_each_user_their_own_file():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        sample = SAMPLE
        binary = b"\x7fELF\x00\x01" + sample.encode() + b"\x00tail"

        # A file without the sample flag is refused and nothing is created.
        r = _create(admin, delivery="replace", upload_source=_upload("crackme", b"\x7fELF no flag"))
        assert r.status_code == 500 and "does not contain the sample flag" in r.get_json()["errors"][""][0]
        assert PersonalChallenge.query.count() == 0
        r = _create(admin, delivery="replace")
        assert r.status_code == 500 and "Upload the file" in r.get_json()["errors"][""][0]

        challenge_id = _create(admin, delivery="replace", upload_source=_upload("crackme", binary)).get_json()["data"]["id"]
        assert PersonalChallenge.query.get(challenge_id).filename == "crackme"

        # Editing other fields keeps the file; changing the template needs a matching file.
        assert admin.patch(f"/api/v1/challenges/{challenge_id}", json={"name": "renamed", "delivery": "replace"}).status_code == 200
        r = admin.patch(f"/api/v1/challenges/{challenge_id}", json={"flag_template": "flag{new_{team}}"})
        assert r.status_code == 500 and "does not contain the sample flag" in r.get_json()["errors"][""][0]
        assert PersonalChallenge.query.get(challenge_id).flag_template == TEMPLATE

        register_user(app, name="alice", email="alice@example.com")
        alice = login_as_user(app, name="alice")
        body = alice.get(f"/download/{challenge_id}").data
        expected = flag_for(PersonalChallenge.query.get(challenge_id), 2).encode()
        assert expected in body and sample.encode() not in body
        assert len(body) == len(binary)  # same-length swap keeps offsets intact

        view = alice.get(f"/api/v1/challenges/{challenge_id}").get_json()["data"]["view"]
        assert f"/download/{challenge_id}" in view
    destroy_ctfd(app)


def test_replace_mode_rewrites_zip_members():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        sample = SAMPLE
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("notes/flag.txt", f"the flag is {sample}\n")
            z.writestr("readme.md", "nothing here")
        challenge_id = _create(
            admin, delivery="replace", upload_source=_upload("bundle.zip", archive.getvalue())
        ).get_json()["data"]["id"]

        register_user(app, name="alice", email="alice@example.com")
        alice = login_as_user(app, name="alice")
        with zipfile.ZipFile(io.BytesIO(alice.get(f"/download/{challenge_id}").data)) as z:
            text = z.read("notes/flag.txt").decode()
        assert flag_for(PersonalChallenge.query.get(challenge_id), 2) in text
    destroy_ctfd(app)


def test_variants_assign_one_answer_per_user_and_catch_other_answers():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        import json

        one = json.dumps([{"description": "Find city A", "answer": "Paris"}])
        r = _create(admin, delivery="variants", flag_template="", variants_json=one)
        assert r.status_code == 500 and "at least two" in r.get_json()["errors"][""][0]
        same = json.dumps([{"description": "A", "answer": "Paris"}, {"description": "B", "answer": " paris "}])
        assert "same answer" in _create(admin, delivery="variants", flag_template="", variants_json=same).get_json()["errors"][""][0]
        rows = json.dumps([
            {"description": "Find city A", "answer": "Paris"}, {"description": "Find city B", "answer": "Tokyo"},
            {"description": "Find city C", "answer": "Lima"}, {"description": "", "answer": ""},
        ])
        challenge_id = _create(admin, delivery="variants", flag_template="", variants_json=rows).get_json()["data"]["id"]
        assert len(PersonalChallenge.query.get(challenge_id).variants) == 3
        for i in range(6):
            register_user(app, name=f"p{i}", email=f"p{i}@example.com")
        challenge = PersonalChallenge.query.get(challenge_id)
        answers = ["Paris", "Tokyo", "Lima"]
        by_variant = {}
        for user_id in range(2, 8):
            by_variant.setdefault(variant_index(challenge, user_id), user_id)
        own_variant, user_id = next(iter(by_variant.items()))
        other_answer = answers[(own_variant + 1) % 3]

        client = login_as_user(app, name=f"p{user_id - 2}")
        assert _attempt(client, challenge_id, other_answer)["message"] == "Incorrect"
        assert ShareEvent.query.one().variant == (own_variant + 1) % 3
        assert _attempt(client, challenge_id, "  " + answers[own_variant].upper() + " ")["status"] == "correct"
    destroy_ctfd(app)


def test_monitor_pages_and_flag_lookup():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        challenge_id = _create(admin).get_json()["data"]["id"]
        register_user(app, name="alice", email="alice@example.com")
        register_user(app, name="bob", email="bob@example.com")
        alice_flag = flag_for(PersonalChallenge.query.get(challenge_id), 2)
        _attempt(login_as_user(app, name="bob"), challenge_id, alice_flag)
        assert Submissions.query.count() == 1

        for section in ("alerts", "submissions", "lookup", "ips", "challenges"):
            assert admin.get(f"/admin/flagprint?section={section}").status_code == 200
        alerts = admin.get("/admin/flagprint?section=alerts").get_data(as_text=True)
        assert "bob" in alerts and "alice" in alerts and alice_flag in alerts
        lookup = admin.get(f"/admin/flagprint?section=lookup&flag={alice_flag}").get_data(as_text=True)
        assert "Issued to" in lookup and "alice" in lookup
        # The old separate page now sends admins to the challenge's own edit page, which has everything.
        old = admin.get(f"/admin/flagprint/challenge/{challenge_id}")
        assert old.status_code == 302 and old.location.endswith(f"/admin/challenges/{challenge_id}")
        assert (ASSETS + "team_flags.js").encode() in admin.get(f"/admin/challenges/{challenge_id}").data

        player = login_as_user(app, name="bob")
        assert player.get("/admin/flagprint").status_code in (302, 403)
    destroy_ctfd(app)


def _docker_available():
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker is required for generator scripts")
def test_script_mode_runs_generator_in_sandbox():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        script = (
            b"import os, pathlib, socket\n"
            b"try:\n    socket.create_connection(('1.1.1.1', 53), timeout=2); net = b'net'\n"
            b"except OSError:\n    net = b'nonet'\n"
            b"pathlib.Path(os.environ['OUTPUT_DIR'], 'out.txt').write_bytes(os.environ['FLAG'].encode() + b'|' + net)\n"
        )
        broken = b"raise SystemExit('boom: cover image missing')\n"
        r = _create(admin, delivery="script", upload_script=_upload("generate.py", broken), output_name="secret.txt")
        assert r.status_code == 500 and "boom: cover image missing" in r.get_json()["errors"][""][0]
        assert PersonalChallenge.query.count() == 0

        challenge_id = _create(
            admin, delivery="script", upload_script=_upload("generate.py", script), output_name="secret.txt",
        ).get_json()["data"]["id"]

        register_user(app, name="alice", email="alice@example.com")
        alice = login_as_user(app, name="alice")
        body = alice.get(f"/download/{challenge_id}").data
        assert body == flag_for(PersonalChallenge.query.get(challenge_id), 2).encode() + b"|nonet"
    destroy_ctfd(app)


def test_hall_of_shame_auto_entries_settings_and_manual_entries():
    from CTFd.plugins.flagprint.models import ShameEntry

    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        challenge_id = _create(admin).get_json()["data"]["id"]
        register_user(app, name="alice", email="alice@example.com")
        register_user(app, name="bob", email="bob@example.com")
        alice_flag = flag_for(PersonalChallenge.query.get(challenge_id), 2)
        bob = login_as_user(app, name="bob")

        _attempt(bob, challenge_id, alice_flag)
        _attempt(bob, challenge_id, alice_flag)
        entries = ShameEntry.query.all()
        assert len(entries) == 1  # one automatic entry per team and challenge
        assert (entries[0].account_id, entries[0].source) == (3, "auto")

        # Off by default: hidden from players, previewable by admins.
        assert bob.get("/hall-of-shame").status_code == 404
        assert "Preview" in admin.get("/hall-of-shame").get_data(as_text=True)

        def post(**form):
            form["nonce"] = _nonce(admin)
            return admin.post("/admin/flagprint/shame", data=form)

        post(action="settings", enabled="on", auto="on")
        page = bob.get("/hall-of-shame").get_data(as_text=True)
        assert "bob" in page and "Got caught on" in page

        post(action="add", account_id="2", reason="Posted flags in a public channel")
        assert ShameEntry.query.filter_by(source="manual").count() == 1
        assert "Posted flags in a public channel" in bob.get("/hall-of-shame").get_data(as_text=True)

        auto_id = ShameEntry.query.filter_by(source="auto").first().id
        post(action="toggle", entry_id=str(auto_id))
        assert "Got caught on" not in bob.get("/hall-of-shame").get_data(as_text=True)
        post(action="delete", entry_id=str(auto_id))
        assert ShameEntry.query.filter_by(id=auto_id).first() is None

        # With auto-add off, a new share is still logged but not listed.
        post(action="settings", enabled="on")
        _attempt(login_as_user(app, name="alice"), challenge_id, flag_for(PersonalChallenge.query.get(challenge_id), 3))
        assert ShareEvent.query.count() == 3
        assert ShameEntry.query.filter_by(source="auto").count() == 0

        assert bob.post("/admin/flagprint/shame", data={"action": "settings", "nonce": _nonce(bob)}).status_code in (302, 403)
        assert ShameEntry.query.count() == 1
    destroy_ctfd(app)


@pytest.mark.skipif(not _docker_available(), reason="Docker is required for generator scripts")
def test_script_input_file_and_download_name_are_separate_and_bad_updates_change_nothing():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        script = (
            b"import os, pathlib\n"
            b"cover = pathlib.Path(os.environ['INPUT']).read_bytes()\n"
            b"pathlib.Path(os.environ['OUTPUT_DIR'], os.environ['OUTPUT_NAME']).write_bytes(cover + os.environ['FLAG'].encode())\n"
        )
        challenge_id = _create(
            admin, delivery="script", output_name="image.png",
            upload_script=_upload("generate.py", script), upload_input=_upload("cover.bin", b"COVER:"),
        ).get_json()["data"]["id"]

        # Renaming the download keeps the input file (they used to share one setting).
        assert admin.patch(f"/api/v1/challenges/{challenge_id}", json={"output_name": "renamed.png"}).status_code == 200
        register_user(app, name="alice", email="alice@example.com")
        alice = login_as_user(app, name="alice")
        challenge = PersonalChallenge.query.get(challenge_id)
        response = alice.get(f"/download/{challenge_id}")
        assert response.data == b"COVER:" + flag_for(challenge, 2).encode()
        assert "renamed.png" in response.headers["Content-Disposition"]

        # A broken new script is refused and the working one stays.
        r = admin.patch(f"/api/v1/challenges/{challenge_id}", json={"upload_script": _upload("generate.py", b"1/0\n")})
        assert r.status_code == 500 and "ZeroDivisionError" in r.get_json()["errors"][""][0]
        preview = admin.get(f"/admin/flagprint/challenge/{challenge_id}/preview?account_id=2")
        assert preview.status_code == 200 and preview.data == b"COVER:" + flag_for(challenge, 2).encode()

        # Removing the input makes this script fail, so that is refused too.
        r = admin.patch(f"/api/v1/challenges/{challenge_id}", json={"remove_input": "1"})
        assert r.status_code == 500 and "generate.py failed" in r.get_json()["errors"][""][0]
    destroy_ctfd(app)


def test_team_flags_list_and_regenerate():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        binary = b"HEAD" + SAMPLE.encode() + b"TAIL"
        challenge_id = _create(admin, delivery="replace", upload_source=_upload("crackme", binary)).get_json()["data"]["id"]
        register_user(app, name="alice", email="alice@example.com")
        register_user(app, name="bob", email="bob@example.com")
        alice, bob = login_as_user(app, name="alice"), login_as_user(app, name="bob")
        challenge = PersonalChallenge.query.get(challenge_id)
        old_alice = flag_for(challenge, 2)

        bob_old_file = bob.get(f"/download/{challenge_id}").data
        _attempt(bob, challenge_id, old_alice)  # bob copies alice's flag
        _attempt(alice, challenge_id, "flag{nope}")

        data = admin.get(f"/admin/flagprint/flags/{challenge_id}").get_json()
        rows = {r["name"]: r for r in data["rows"]}
        assert data["challenge"]["mode"] == "replace" and data["challenge"]["file"] == "crackme"
        assert rows["alice"]["flag"] == old_alice and rows["alice"]["leaked"] == 1 and rows["alice"]["fails"] == 1
        assert rows["bob"]["copied"] == 1 and rows["bob"]["file"].endswith("account_id=3")

        # Regenerate alice: her old flag stops working for her, and anyone else using it is still caught.
        assert admin.post(f"/admin/flagprint/flags/{challenge_id}/regenerate", json={"account_id": 2}).get_json()["count"] == 1
        new_alice = flag_for(challenge, 2)
        rows = {r["name"]: r for r in admin.get(f"/admin/flagprint/flags/{challenge_id}").get_json()["rows"]}
        assert new_alice != old_alice and rows["alice"]["version"] == 1 and rows["alice"]["flag"] == new_alice
        assert _attempt(alice, challenge_id, old_alice)["status"] == "incorrect"
        assert ShareEvent.query.count() == 1  # her own old flag is not "sharing"
        assert _attempt(bob, challenge_id, old_alice)["status"] == "incorrect"
        assert ShareEvent.query.count() == 2  # but bob using it still is
        assert new_alice.encode() in alice.get(f"/download/{challenge_id}").data
        assert _attempt(alice, challenge_id, new_alice)["status"] == "correct"

        # Regenerate all: bob gets a new flag and a rebuilt file.
        admin.post(f"/admin/flagprint/flags/{challenge_id}/regenerate", json={"all": True})
        assert bob.get(f"/download/{challenge_id}").data != bob_old_file
        lookup = admin.get(f"/admin/flagprint?section=lookup&flag={old_alice}").get_data(as_text=True)
        assert "alice" in lookup

        assert admin.post(f"/admin/flagprint/flags/{challenge_id}/regenerate", json={"account_id": 999}).status_code == 404
        assert alice.get(f"/admin/flagprint/flags/{challenge_id}").status_code in (302, 403)
        assert alice.post(f"/admin/flagprint/flags/{challenge_id}/regenerate", json={"all": True}).status_code in (302, 403)
        standard = admin.post("/api/v1/challenges", json={"name": "s", "category": "x", "description": "x", "value": 1, "type": "standard"}).get_json()["data"]["id"]
        assert admin.get(f"/admin/flagprint/flags/{standard}").status_code == 404
    destroy_ctfd(app)


def test_regenerate_resets_the_team_on_the_challenge_and_the_scoreboard():
    from CTFd.models import Fails, Users

    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        challenge_id = _create(admin).get_json()["data"]["id"]  # flag-only, 100 points
        register_user(app, name="alice", email="alice@example.com")
        register_user(app, name="bob", email="bob@example.com")
        alice, bob = login_as_user(app, name="alice"), login_as_user(app, name="bob")
        challenge = PersonalChallenge.query.get(challenge_id)

        _attempt(alice, challenge_id, "flag{wrong}")
        _attempt(bob, challenge_id, flag_for(challenge, 2))  # bob copies alice: logged
        assert _attempt(alice, challenge_id, flag_for(challenge, 2))["status"] == "correct"
        assert _attempt(bob, challenge_id, flag_for(challenge, 3))["status"] == "correct"

        def score(name):
            return Users.query.filter_by(name=name).first().get_score()

        def board():
            return {row["name"]: row["score"] for row in admin.get("/api/v1/scoreboard").get_json()["data"]}

        assert score("alice") == 100 and board()["alice"] == 100

        # Regenerate alice: her solve, points and attempts go; bob is untouched; the share alert stays.
        r = admin.post(f"/admin/flagprint/flags/{challenge_id}/regenerate", json={"account_id": 2}).get_json()
        assert r["removed"] == {"solves": 1, "attempts": 1}
        assert score("alice") == 0 and board().get("alice", 0) == 0 and board()["bob"] == 100
        assert Fails.query.filter_by(challenge_id=challenge_id, user_id=2).count() == 0
        assert ShareEvent.query.count() == 1
        assert _attempt(alice, challenge_id, flag_for(challenge, 2))["status"] == "correct"  # can solve again
        assert score("alice") == 100

        # Regenerate all: the challenge is fresh for everyone.
        r = admin.post(f"/admin/flagprint/flags/{challenge_id}/regenerate", json={"all": True}).get_json()
        assert r["removed"]["solves"] == 2
        assert Solves.query.filter_by(challenge_id=challenge_id).count() == 0
        assert board().get("alice", 0) == 0 and board().get("bob", 0) == 0
        assert ShareEvent.query.count() == 1
    destroy_ctfd(app)


@pytest.mark.skipif(not _docker_available(), reason="Docker is required for generator scripts")
def test_script_that_checks_the_flag_format_is_accepted():
    # Real scripts often refuse anything but a real-looking flag; the save-time test run must pass them.
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        strict = (
            b"import os, re, pathlib\n"
            b"flag = os.environ['FLAG']\n"
            b"if not re.fullmatch(r'flag\\{[a-z0-9_]+\\}', flag):\n"
            b"    raise ValueError('FLAG must use lowercase flag{...} format')\n"
            b"pathlib.Path(os.environ['OUTPUT_DIR'], 'out.txt').write_text(flag)\n"
        )
        r = _create(admin, flag_template="flag{str1ct_{team}}", delivery="script",
                    upload_script=_upload("generate.py", strict), output_name="out.txt")
        assert r.status_code == 200, r.get_json()
    destroy_ctfd(app)


@pytest.mark.skipif(not _docker_available(), reason="Docker is required for generator scripts")
def test_rev_generator_can_compile_a_binary_per_team():
    from CTFd.plugins.flagprint import files

    if not set(files.SANDBOX_IMAGES) & _docker_images():
        pytest.skip("the Flagprint sandbox image is not on this machine")
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        script = (
            b"import os, pathlib, subprocess\n"
            b"src = '#include <stdio.h>\\nint main(){puts(\"%s\");return 0;}' % os.environ['FLAG']\n"
            b"pathlib.Path('/tmp/a.c').write_text(src)\n"
            b"out = pathlib.Path(os.environ['OUTPUT_DIR'], os.environ['OUTPUT_NAME'])\n"
            b"subprocess.run(['gcc', '-o', str(out), '/tmp/a.c'], check=True)\n"
        )
        r = _create(admin, flag_template="flag{gcc_{team}}", delivery="script",
                    upload_script=_upload("generate.py", script), output_name="chall")
        assert r.status_code == 200, r.get_json()
        register_user(app, name="alice", email="alice@example.com")
        binary = login_as_user(app, name="alice").get(f"/download/{r.get_json()['data']['id']}").data
        assert binary[:4] == b"\x7fELF"
        assert flag_for(PersonalChallenge.query.get(r.get_json()["data"]["id"]), 2).encode() in binary
    destroy_ctfd(app)


def _docker_images():
    try:
        import docker
        return {tag for image in docker.from_env().images.list() for tag in image.tags}
    except Exception:
        return set()


def test_new_challenge_never_serves_files_left_from_an_older_one():
    from CTFd.plugins.flagprint import files

    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        # A file issued under id 1 before a reset of the database.
        stale = files.account_path(type("C", (), {"id": 1, "filename": "note.txt"}), 2)
        import os
        os.makedirs(os.path.dirname(stale), exist_ok=True)
        with open(stale, "wb") as handle:
            handle.write(b"old challenge")
        r = _create(admin, delivery="replace", upload_source=_upload("note.txt", b"flag: " + SAMPLE.encode()))
        assert r.get_json()["data"]["id"] == 1
        register_user(app, name="alice", email="alice@example.com")
        data = login_as_user(app, name="alice").get("/download/1").data
        assert data == b"flag: " + flag_for(PersonalChallenge.query.get(1), 2).encode()
    destroy_ctfd(app)


def test_hall_of_shame_menu_link_follows_the_setting():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        register_user(app)
        user = login_as_user(app)
        assert "/hall-of-shame" not in user.get("/challenges").get_data(as_text=True)
        admin = login_as_user(app, name="admin")
        admin.post("/admin/flagprint/shame", data={"action": "settings", "enabled": "on", "nonce": _nonce(admin)})
        assert "/hall-of-shame" in user.get("/challenges").get_data(as_text=True)
        assert user.get("/hall-of-shame").status_code == 200
        admin.post("/admin/flagprint/shame", data={"action": "settings", "nonce": _nonce(admin)})
        assert "/hall-of-shame" not in user.get("/challenges").get_data(as_text=True)
        assert user.get("/hall-of-shame").status_code == 404
    destroy_ctfd(app)


def test_download_needs_prerequisites_and_a_file():
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        first = _create(admin, name="first").get_json()["data"]["id"]
        second = _create(admin, name="second", delivery="replace", upload_source=_upload("n.txt", SAMPLE.encode()),
                         requirements={"prerequisites": [first]}).get_json()["data"]["id"]
        register_user(app, name="alice", email="alice@example.com")
        alice = login_as_user(app, name="alice")
        assert alice.get(f"/download/{first}").status_code == 404  # flag-only: nothing to download
        assert alice.get(f"/download/{second}").status_code == 403  # locked until "first" is solved
        assert _attempt(alice, first, flag_for(PersonalChallenge.query.get(first), 2))["status"] == "correct"
        assert alice.get(f"/download/{second}").status_code == 200
    destroy_ctfd(app)


def test_flag_secret_is_created_once_and_shared():
    from CTFd.models import Configs
    from CTFd.plugins.flagprint.flags import SECRET_CONFIG_KEY, _secret

    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        rows = Configs.query.filter_by(key=SECRET_CONFIG_KEY).all()
        assert len(rows) == 1 and len(rows[0].value) == 64  # made at startup, not on the first flag
        assert _secret() == rows[0].value.encode()
        app._flagprint_secret = None  # a second worker starting up reads the same row
        assert _secret() == rows[0].value.encode()
    destroy_ctfd(app)


@pytest.mark.skipif(not _docker_available(), reason="Docker is required for generator scripts")
def test_fallback_image_failures_always_carry_the_pull_hint(monkeypatch):
    from CTFd.plugins.flagprint import files

    monkeypatch.setattr(files, "SANDBOX_IMAGES", ["flagprint/does-not-exist:never"])
    assert files.sandbox_status()["ok"] is False
    with pytest.raises(files.GenerationError) as caught:
        files.run_script(b"from PIL import Image\n", "x.bin", "flag{t3st_0123456789ab}")
    message = str(caught.value)
    assert "ModuleNotFoundError" in message and "docker pull" in message and files.FALLBACK_IMAGE in message


def test_sandbox_status_is_shown_on_the_edit_page():
    # The create form is rendered client-side by nunjucks; the edit page is server-rendered jinja,
    # so the sandbox status (a plugin jinja global) appears there.
    app = create_ctfd(enable_plugins=True)
    with app.app_context():
        admin = login_as_user(app, name="admin")
        challenge_id = _create(admin).get_json()["data"]["id"]
        page = admin.get(f"/admin/challenges/{challenge_id}").get_data(as_text=True)
        from CTFd.plugins.flagprint import files
        assert files.sandbox_status()["detail"] in page
    destroy_ctfd(app)
