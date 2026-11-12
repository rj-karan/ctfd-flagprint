<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="Flagprint" width="320">
  </picture>
</p>

<p align="center"><b>Every team gets its own flag and its own files.<br>A shared flag tells you who leaked it.</b></p>

<p align="center">An anti flag-sharing plugin for CTFd: unique flags per team, per-team challenge files,<br>and shared-flag detection that names the leaker.</p>

<p align="center">
  <a href="https://github.com/rj-karan/ctfd-flagprint/actions/workflows/tests.yml"><img src="https://github.com/rj-karan/ctfd-flagprint/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/rj-karan/ctfd-flagprint/releases/latest"><img src="https://img.shields.io/github/v/release/rj-karan/ctfd-flagprint?label=release" alt="latest release"></a>
  <img src="https://img.shields.io/badge/CTFd-3.8-blue" alt="CTFd 3.8">
  <a href="https://github.com/rj-karan/ctfd-flagprint/pkgs/container/flagprint-generator"><img src="https://img.shields.io/badge/ghcr.io-sandbox%20image-2496ED?logo=docker&logoColor=white" alt="sandbox image on ghcr.io"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="Apache 2.0"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#create-a-per-team-challenge">Create a challenge</a> ·
  <a href="#writing-generatepy">generate.py</a> ·
  <a href="#admin-monitor">Admin monitor</a> ·
  <a href="#compared-with-other-options">Compared with</a> ·
  <a href="#development">Development</a>
</p>

<br>

<p align="center">
  <img src="docs/images/demo.gif" alt="A team pastes another team's flag, sees Incorrect, and the admin is told who copied whose flag" width="880">
</p>

<br>

Flagprint is a plugin for [CTFd](https://github.com/CTFd/CTFd). Each team gets a flag nobody else has, usually inside
a file built just for them. When Team B submits Team A's flag, Team B sees a plain "Incorrect". You see who copied,
whose flag it was, and when.

## Why

In any CTF with prizes, someone pastes a flag into a group chat. With one static flag per challenge you never find out.
CTFd's own per-user flags are Enterprise-only and only for hosted containers, while most challenges are files: an
image, a pcap, a binary, a zip. Flagprint gives those files per-team flags too, on the open-source CTFd you already run.

## What you get

| | |
|---|---|
| **Per-team flags** | Write `flag{st3g0_l0v3s_y0u_{team}}`. Each team's `{team}` becomes a 12-character code, an HMAC of the challenge and the team. No flag table to fill in or keep in sync. |
| **Per-team files** | **Replace:** upload a file holding a sample flag and each team downloads a copy with their own. Works on text, binaries, pcaps and inside zips. **Script:** upload a `generate.py` and it builds each team's file in an offline sandbox: stego images, compiled crackmes, encrypted blobs. |
| **Variants** | For fixed-answer tasks (OSINT, trivia) each team gets one of several versions. Another version's answer counts as sharing. |
| **Who leaked it** | A wrong submission that matches another team's flag is logged with both teams, the player, IP and time, and pops up on every admin page. |
| **Admin monitor** | Share alerts, every submission with its owner, flag lookup, teams sharing an IP, an optional Hall of Shame. |
| **Team flags panel** | On each challenge: every team's flag, their exact file, solve and sharing counts, and **Regenerate** when a flag leaks. |
| **Quiet by default** | The type shows as `classic`, players never see the template, and under a neutral folder name nothing player-facing mentions Flagprint. |

## How it works

```
template       flag{st3g0_l0v3s_y0u_{team}}
team code      HMAC-SHA256(secret, "challenge_id:team_id")[:12]   →  5f1c09a2be47
Team A's flag  flag{st3g0_l0v3s_y0u_5f1c09a2be47}
```

When a submission is wrong but fits the template, Flagprint checks the code against every team's. If it belongs to
someone else, that's a share: logged for you, "Incorrect" for them. The secret lives in your database, so flags stay
the same across restarts and don't depend on `SECRET_KEY`.

## Install

```bash
cd CTFd/CTFd/plugins
git clone https://github.com/rj-karan/ctfd-flagprint flagprint
```

Restart CTFd. The tables are created on startup. Open **Admin → Flagprint** and create a challenge of type
**classic**. That's all you need for flag, replace and variants delivery.

<details>
<summary><b>Script delivery</b> (generate.py) needs Docker</summary>

<br>

The sandbox image is published on GitHub Container Registry, so you pull it rather than build it:

```bash
docker pull ghcr.io/rj-karan/flagprint-generator:latest
```

It has Python 3.12 with Pillow and PyCryptodome, gcc/g++ (including `-m32` and static musl builds), rustc, nasm,
binutils, patchelf and upx. Without it, scripts run in plain `python:3.12-slim`. To use your own image, set
`FLAGPRINT_SANDBOX_IMAGE`; to build this one yourself, `docker build -t flagprint/generator:latest generator`.

The CTFd process also needs the Python docker client (`requirements.txt`, installed automatically when CTFd's Docker
image is built) and access to the Docker socket. With CTFd's `docker-compose.yml`, copy
[`docs/docker-compose.override.yml`](docs/docker-compose.override.yml) next to it and run:

```bash
DOCKER_GID=$(getent group docker | cut -d: -f3) docker compose up -d --build
```

> Mounting the Docker socket gives CTFd control of the host's Docker. Only script delivery needs it; skip it otherwise.

</details>

<details>
<summary><b>Hide it from players</b></summary>

<br>

Asset paths follow the folder name, and players can see those paths in the challenge API. Clone into a neutral name
and the plugin becomes invisible, so sharers get caught rather than warned:

```bash
git clone https://github.com/rj-karan/ctfd-flagprint classic
```

Or keep the name and use it as a deterrent. Both work.

</details>

## Create a per-team challenge

**Admin → Challenges → New → classic**, then choose how teams get their flag:

| Delivery | Use it for | You upload |
|---|---|---|
| Replace | Files that hold the flag as-is: text, pcap, binary, zip | The file, containing the sample flag shown under the template |
| Script | Files that must be built: stego, crackmes, encrypted data | `generate.py`, plus an optional input file |
| Flag only | Services and instances that print the flag themselves | Nothing |
| Variants | Fixed answers: OSINT, trivia | Two or more task texts with their answers |

Write the template with `{team}` exactly once, e.g. `flag{n0t_y0ur_fl4g_{team}}`, and save. Script delivery test-runs
your script before anything is saved, so a broken script never reaches players.

<p align="center">
  <img src="docs/images/script-form.png" alt="The per-team settings on a challenge's edit page" width="620">
</p>

Players download their file from the challenge window as usual:

<p align="center">
  <img src="docs/images/player-download.png" alt="A challenge window with the team's own evidence.zip download" width="440">
</p>

## Writing generate.py

Your script gets four environment variables and writes one file into `OUTPUT_DIR`:

| Variable | Value |
|---|---|
| `FLAG` | This team's flag |
| `INPUT` | Path of the optional input file, or empty |
| `OUTPUT_DIR` | Folder to write the result into |
| `OUTPUT_NAME` | The download name you chose, e.g. `image.png` |

It runs with no network, all capabilities dropped, 1 GB of memory and a 3-minute limit. Each team's file is built on
their first download and cached. Three complete examples:

- [`examples/stego_png.py`](examples/stego_png.py) hides the flag in the low bits of a cover image.
- [`examples/rev_binary.py`](examples/rev_binary.py) compiles a crackme with the flag XOR-encoded inside.
- [`examples/forensics_layers.py`](examples/forensics_layers.py) builds a zip with a log and a SQLite database, the
  flag three layers down behind a per-team key.

**[Writing generate.py](docs/GENERATE.md)** has the full contract, the six rules that keep scripts working for a
thousand teams, and a copy-paste prompt for letting an AI assistant write the script from your existing challenge
file. Try a script before uploading with `python tools/try_generate.py generate.py`.

## Admin monitor

<p align="center">
  <img src="docs/images/share-alerts.png" alt="Share alerts: who submitted whose flag, on which challenge, with IP and time">
</p>

**Admin → Flagprint** has six tabs:

- **Share alerts:** every time a team submitted another team's flag.
- **All submissions** to per-team challenges, each with whose flag it was.
- **Flag lookup:** paste a flag from a writeup or a Discord screenshot and see which team it was issued to.
- **Shared IPs:** addresses used by more than one team. A lead, not proof.
- **Hall of Shame:** the public page on or off, auto-add caught teams, add or hide entries by hand.
- **Per-team challenges:** every challenge that uses per-team flags.

<p align="center">
  <img src="docs/images/flag-lookup.png" alt="Flag lookup shows which team a flag was issued to">
</p>

Each per-team challenge's edit page gets a **Team flags** panel: every team's flag, a download of their exact file,
solve status, how often their flag leaked or they used someone else's, and **Regenerate**, which gives one team (or
everyone) a new flag and resets their solve on that challenge.

<p align="center">
  <img src="docs/images/team-flags.png" alt="Team flags panel: each team's flag, solve, leaked and copied counts, file download and Regenerate">
</p>

New shares pop up on whatever admin page you're on:

<p align="center">
  <img src="docs/images/alert-toast.png" alt="Flag sharing caught: Root Cause submitted Null Pointers' flag on Exfil" width="440">
</p>

## Compared with other options

| | Per-team flags | Per-team **files** | Names the leaker | CTFd 3.8 | Free |
|---|:---:|:---:|:---:|:---:|:---:|
| **Flagprint** | ✓ | ✓ any file type, or a script | ✓ | ✓ | ✓ |
| CTFd Application Target | ✓ | containers only | ✓ | ✓ | Enterprise |
| [ctfd-warden](https://github.com/0xZyyz/ctfd-warden) | needs them from elsewhere | – | ✓ | ✓ | ✓ |
| Container instancers ([CTFd-Docker-Plugin](https://github.com/phannhat17/CTFd-Docker-Plugin), [RedHerring](https://github.com/Isotech42/CTFd-RedHerring)) | ✓ | containers only | some | varies | ✓ |
| [ctfd-dynamic-flag](https://github.com/defojeco/ctfd-dynamic-flag) | ✓ hashed | – | – | ✓ | ✓ |
| [CTFd_unique_challenges](https://github.com/Gerrit0/CTFd_unique_challenges) | ✓ | text only | – | 2.2 | ✓ |

Flagprint and Warden go well together: Flagprint makes the flags unique and attributes leaks, Warden watches for bots,
shared accounts and suspicious solve speed.

## Works with other plugins

An instancer or any plugin that issues its own per-team flags can join the monitor, lookup and share logging:

```python
from CTFd.plugins.flagprint import ON_REGENERATE, PER_TEAM_SOURCES, TEAM_FLAG_EXTRAS, record_if_shared
from CTFd.plugins.flagprint.flags import classify, flag_for

# Your challenge model needs flag_template (with {team}) and delivery = "flag".
PER_TEAM_SOURCES.append(lambda: MyContainerChallenge.query.all())
TEAM_FLAG_EXTRAS.append(lambda challenge, account_ids: {})  # extra columns for the Team flags panel
ON_REGENERATE.append(lambda challenge, account_ids: None)   # e.g. stop instances holding the old flag

# Give each instance flag_for(challenge, account_id), check answers with classify(...),
# and call record_if_shared(user, team, challenge, request) from your challenge type's fail().
```

## Limits

Flagprint catches **flags** that move between teams. It can't stop a team sharing a writeup or a solve script that
each team then runs on its own file. For that, make the files differ in more than the flag: a random key, offset or
layout chosen in `generate.py`.

## Compatibility

CTFd 3.8.x, teams mode and users mode. CI runs the suite against CTFd 3.8.7 and 3.8.9 on SQLite; MariaDB is used in
production. PostgreSQL should work but is untested.

## Development

```bash
git clone https://github.com/CTFd/CTFd && cd CTFd
pip install -r requirements.txt pytest docker
git clone https://github.com/rj-karan/ctfd-flagprint CTFd/plugins/flagprint
mkdir tests/flagprint && touch tests/flagprint/__init__.py
cp CTFd/plugins/flagprint/tests/test_flagprint.py tests/flagprint/
python -m pytest tests/flagprint -p no:randomly
```

Tests that run `generate.py` need Docker and are skipped without it. See [CONTRIBUTING.md](CONTRIBUTING.md) for how
to send changes and [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Support

If Flagprint helped your event, star the repo so other organizers find it, and tell us how it went in
[Discussions](https://github.com/rj-karan/ctfd-flagprint/discussions).

## License

[Apache 2.0](LICENSE). Copyright 2026 [KARAN RJ](https://github.com/rj-karan).
