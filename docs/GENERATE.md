# Writing generate.py

Script delivery runs your `generate.py` once per team and hands that team the file it writes. This page is the whole
contract, the habits that keep scripts working for a thousand teams, and a prompt you can give an AI assistant when
you'd rather not write it yourself.

## The contract

Your script runs in an offline container with four environment variables and must write **one file** into
`OUTPUT_DIR`:

| Variable | Value | Example |
|---|---|---|
| `FLAG` | This team's flag, already in your format | `flag{dns_3xf1l_5f1c09a2be47}` |
| `INPUT` | Path of the optional input file you uploaded, or empty | `/work/input/cover.png` |
| `OUTPUT_DIR` | Folder to write into | `/work/out` |
| `OUTPUT_NAME` | The download name you chose in the form | `evidence.zip` |

Rules the sandbox enforces: no network, all capabilities dropped, 1 GB of memory, 256 processes, 3 minutes. Exit
with a non-zero code to fail; whatever you print to stderr is shown to the admin. Nothing is cached between runs.

Tools in the sandbox image (`ghcr.io/rj-karan/flagprint-generator`): Python 3.12 with Pillow and PyCryptodome;
gcc and g++ (also `-m32` and static builds with musl), rustc, nasm, binutils (`strip`, `objcopy`), patchelf, upx,
zip, unzip, file, xxd. No `pip install` at run time: if you need a library that isn't there, build your own image
and point `FLAGPRINT_SANDBOX_IMAGE` at it.

When the script is saved, Flagprint test-runs it once with a realistic flag. If it fails, the challenge is not saved
and you see the error.

## A shape that works

```python
import hashlib, os, random

flag = os.environ["FLAG"]
rng = random.Random(hashlib.sha256(b"my-challenge:" + flag.encode()).digest())  # see rule 1

def build(flag: str, rng: random.Random, input_path: str | None) -> bytes:
    ...  # everything that makes the file lives here
    return data

output = os.path.join(os.environ["OUTPUT_DIR"], os.environ["OUTPUT_NAME"] or "challenge.bin")
with open(output, "wb") as handle:
    handle.write(build(flag, rng, os.environ.get("INPUT") or None))
```

Keep `build()` pure: flag in, bytes out. That makes it easy to run locally, test, and reason about.

## Six rules

1. **Seed randomness from the flag.** `random.Random(sha256(flag))`, never bare `random` or `secrets`, for anything
   that ends up in the file. Then a rebuilt file for the same team is byte-identical, which matters when you edit
   the challenge after people have downloaded it.
2. **Never hardcode the flag's length or shape.** Use `len(flag)`. The flag you get in production has the same
   format as the test flag, but a template edit should not break your script.
3. **Keep the flag out of plain text unless finding it is the point.** For stego, crypto and rev, run
   `strings` on your output before you ship. `tools/try_generate.py` tells you when the flag is visible.
4. **Vary more than the flag.** A per-team flag stops flag sharing. A per-team key, offset or layout also stops
   solve-script sharing: team A's script should not work on team B's file. Draw those from the seeded `rng`.
5. **Fail loudly.** Check what you assume (`INPUT` exists, the compiler succeeded, the output is non-empty) and
   `sys.exit("why")` when it doesn't. A silent half-built file reaches players; an error reaches you.
6. **Stay inside the budget.** Each team's file is built on their first download. If building takes 30 seconds,
   the first download takes 30 seconds. Compile once, don't brute-force, don't write gigabytes.

## Test it on your machine

```bash
python tools/try_generate.py generate.py --name evidence.zip
python tools/try_generate.py generate.py --input cover.png --name image.png
python tools/try_generate.py generate.py --docker          # the real sandbox image and limits
```

It runs your script with a realistic flag, reports the output file and its size, and warns when the flag is visible
in plain text. Then solve the output yourself, exactly as a player would, before uploading.

## Examples in this repository

| Script | Shape | Shows |
|---|---|---|
| [`stego_png.py`](../examples/stego_png.py) | Hidden in an image | Using `INPUT`, bit-level edits with Pillow |
| [`rev_binary.py`](../examples/rev_binary.py) | Compiled crackme | Generating C source and calling `gcc` |
| [`forensics_layers.py`](../examples/forensics_layers.py) | Multi-layer forensics artifact | A seeded `rng`, a per-team key, a zip with a log and a SQLite database, standard library only |

## Letting an AI write it

Most authors already do this; the failures come from the assistant not knowing the contract. Give it the four
things below and the prompt that follows, and it will usually produce a working script on the first try.

**What to give the assistant**

1. **The challenge file you have today**, or the script or source that built it. Attach it or paste it.
2. **The intended solve**, in two or three sentences. "The flag is XOR-encrypted in the pcap's DNS TXT records; the
   key is the MD5 of the hostname" tells the assistant what must stay the same and what may vary per team.
3. **Your flag template and a sample flag**, e.g. `flag{dns_3xf1l_{team}}` and `flag{dns_3xf1l_5f1c09a2be47}`.
4. **The download name** players should get, e.g. `capture.pcap`.

**The prompt** (copy it whole, fill in the brackets):

```
Write a Python 3.12 script named generate.py for a CTF challenge. It will be run once per team, inside an
offline Docker container, to build that team's copy of the challenge file.

The script receives four environment variables:
- FLAG: this team's flag, e.g. [SAMPLE FLAG]. Treat its length and content as unknown; never hardcode them.
- INPUT: path to an optional input file, or an empty string. [SAY WHAT THE INPUT IS, OR "There is no input file."]
- OUTPUT_DIR: a folder. Write exactly one file into it.
- OUTPUT_NAME: the file name to use, e.g. [DOWNLOAD NAME].

Constraints:
- No network, no pip install. Available: Python standard library, Pillow, PyCryptodome, gcc/g++ (including -m32
  and static musl builds), rustc, nasm, strip, objcopy, patchelf, upx, zip. 3 minutes and 1 GB of memory.
- Seed all randomness from the flag: rng = random.Random(hashlib.sha256(flag.encode()).digest()). The same flag
  must always produce the same bytes.
- Besides the flag, vary at least one solving parameter per team (a key, an offset, a layout) drawn from that
  rng, so a solve script written for one team's file does not work on another's.
- The flag must not appear in plain text in the output [UNLESS FINDING IT IS THE POINT: SAY SO].
- Validate your assumptions and exit non-zero with a clear message on stderr if anything fails.
- Write the output atomically at the end; do not leave partial files.

The challenge: [TWO OR THREE SENTENCES: WHAT PLAYERS GET AND HOW THEY ARE MEANT TO SOLVE IT].
Attached: [THE CURRENT CHALLENGE FILE OR THE CODE THAT PRODUCED IT]. Reproduce it faithfully, replacing the
hardcoded flag and any fixed secrets with values derived from FLAG and rng as described.

Return only the complete generate.py, followed by a short solve walkthrough for one team's output so I can
verify it.
```

**What to check in what comes back**

- Run it: `python tools/try_generate.py generate.py --name [DOWNLOAD NAME]`. It must finish, write one file, and
  the plain-text note should match your intent.
- Solve the output by hand once, following the walkthrough. If the walkthrough needs information that is not in
  the file, the challenge is broken.
- Run it twice with the same `--flag`. The two files must be identical (`sha256sum`).
- Run it with two different `--flag` values. The solve must need different values (key, offset) for each.
- Search the script for literal flag strings, fixed keys, or a hardcoded flag length. Replace any you find.

Then upload it in the challenge form. Flagprint test-runs it again before saving.
