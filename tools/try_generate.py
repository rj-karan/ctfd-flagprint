#!/usr/bin/env python3
"""Run a Flagprint generate.py on your own machine, the way CTFd will run it.

    python tools/try_generate.py generate.py
    python tools/try_generate.py generate.py --input cover.png --name image.png
    python tools/try_generate.py generate.py --docker          # inside the real sandbox image

Prints where the output landed, its size, and whether the flag is visible in it as plain text.
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

SANDBOX = os.environ.get("FLAGPRINT_SANDBOX_IMAGE", "ghcr.io/rj-karan/flagprint-generator:latest")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("script", help="your generate.py")
    parser.add_argument("--flag", default="flag{t3st_fl4g_0123456789ab}", help="the FLAG to pass (default: a realistic one)")
    parser.add_argument("--input", help="optional input file, passed as INPUT")
    parser.add_argument("--name", default="output.bin", help="OUTPUT_NAME the players would download")
    parser.add_argument("--out", default="try-output", help="folder to put the result in")
    parser.add_argument("--docker", action="store_true", help=f"run inside {SANDBOX} with the same limits as CTFd")
    args = parser.parse_args()

    script = pathlib.Path(args.script).resolve()
    out_dir = pathlib.Path(args.out).resolve()
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    env = {"FLAG": args.flag, "INPUT": "", "OUTPUT_DIR": str(out_dir), "OUTPUT_NAME": args.name}

    if args.docker:
        mounts = ["-v", f"{script}:/work/generate.py:ro", "-v", f"{out_dir}:/work/out"]
        if args.input:
            source = pathlib.Path(args.input).resolve()
            mounts += ["-v", f"{source}:/work/input/{source.name}:ro"]
            env["INPUT"] = f"/work/input/{source.name}"
        env["OUTPUT_DIR"] = "/work/out"
        command = ["docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--memory", "1g", "--pids-limit", "256", "-w", "/work"]
        for key, value in env.items():
            command += ["-e", f"{key}={value}"]
        command += mounts + [SANDBOX, "python", "generate.py"]
    else:
        if args.input:
            env["INPUT"] = str(pathlib.Path(args.input).resolve())
        command = [sys.executable, str(script)]

    print(f"FLAG={env['FLAG']}  INPUT={env['INPUT'] or '(none)'}  OUTPUT_NAME={env['OUTPUT_NAME']}")
    try:
        result = subprocess.run(command, env={**os.environ, **env}, cwd=tempfile.gettempdir(), timeout=180)
    except subprocess.TimeoutExpired:
        sys.exit("FAILED: the script did not finish within 3 minutes, CTFd's limit.")
    if result.returncode != 0:
        sys.exit(f"FAILED: exit code {result.returncode}. Fix what the script printed above.")

    produced = [p for p in out_dir.iterdir() if p.is_file()]
    if not produced:
        sys.exit(f"FAILED: nothing was written to OUTPUT_DIR ({out_dir}).")
    if len(produced) > 1:
        print(f"WARNING: {len(produced)} files written; CTFd serves only the first one. Write exactly one.")
    output = produced[0]
    data = output.read_bytes()
    print(f"OK: {output} ({len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]}…)")
    if output.name != args.name:
        print(f"NOTE: the file is named {output.name}; players will download it as {args.name}.")
    if args.flag.encode() in data:
        print("NOTE: the flag appears in plain text in the output. Fine for a 'find the file' task; "
              "for stego, crypto or rev, players could just run strings on it.")


if __name__ == "__main__":
    main()
