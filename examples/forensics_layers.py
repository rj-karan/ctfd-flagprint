"""Script delivery example, harder: a forensics artifact with the flag three layers down.

Players get incident.zip holding an application log and a SQLite database. The flag is AES-free on purpose
(standard library only): it is XOR-streamed with a key that is derived from a session token that only appears,
split in two, in the log. Every team gets a different token, key and record ids, so a solve script written for
one team's file does not work on another's.

Upload this as generate.py and set the download name to incident.zip. No input file is needed.
"""
import hashlib
import io
import json
import os
import random
import sqlite3
import tempfile
import zipfile

flag = os.environ["FLAG"].encode()
# Seed everything from the flag: a rebuilt file for the same team is byte-identical.
rng = random.Random(hashlib.sha256(b"forensics-layers:" + flag).digest())

token = "%032x" % rng.getrandbits(128)
key = hashlib.sha256(("sess:" + token).encode()).digest()
cipher = bytes(b ^ key[i % len(key)] for i, b in enumerate(flag))
record_id = rng.randrange(1000, 9000)

# Layer 1: a log where the token is split across two lines among noise.
users = ["m.ortiz", "j.chen", "a.kowalski", "r.okafor", "s.lindqvist", "t.nakamura"]
lines = []
clock = 1792080000 + rng.randrange(0, 86400)
for _ in range(rng.randrange(140, 220)):
    clock += rng.randrange(2, 90)
    user = rng.choice(users)
    kind = rng.choice(["login ok", "login failed", "export requested", "export denied", "settings changed"])
    lines.append(f"{clock} INFO {user} {kind} sid={'%032x' % rng.getrandbits(128)}")
split = rng.randrange(40, len(lines) - 40)
lines.insert(split, f"{clock - 7} WARN svc-backup session resumed sid_head={token[:16]}")
lines.insert(split + rng.randrange(5, 30), f"{clock - 3} WARN svc-backup checkpoint sid_tail={token[16:]} ref={record_id}")
log = "\n".join(lines) + "\n"

# Layer 2: a database where one row among many holds the ciphertext.
with tempfile.TemporaryDirectory() as tmp:
    db_path = os.path.join(tmp, "vault.db")
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE exports (id INTEGER PRIMARY KEY, owner TEXT, created INTEGER, payload BLOB, note TEXT)")
    rows = []
    for _ in range(rng.randrange(60, 120)):
        junk = bytes(rng.getrandbits(8) for _ in range(len(flag)))
        rows.append((rng.randrange(1000, 9000), rng.choice(users), clock - rng.randrange(0, 900000), junk, "routine"))
    rows = [r for r in rows if r[0] != record_id]
    rows.append((record_id, "svc-backup", clock - 5, cipher, "resumed"))
    rng.shuffle(rows)
    db.executemany("INSERT OR IGNORE INTO exports VALUES (?,?,?,?,?)", rows)
    db.commit()
    db.close()
    with open(db_path, "rb") as handle:
        database = handle.read()

# Layer 3: the archive the players download, with a README that frames the story.
readme = json.dumps({
    "case": "backup service exfiltration",
    "note": "The backup service resumed a session it should not have. Find what it exported.",
    "hint": "payload = flag XOR sha256('sess:' + session id), repeating",
}, indent=2)
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("incident/README.json", readme)
    archive.writestr("incident/app.log", log)
    archive.writestr("incident/vault.db", database)

output = os.path.join(os.environ["OUTPUT_DIR"], os.environ["OUTPUT_NAME"] or "incident.zip")
with open(output, "wb") as handle:
    handle.write(buffer.getvalue())
