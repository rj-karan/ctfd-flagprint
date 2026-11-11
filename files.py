"""Per-account challenge files: storage, sample-flag replacement and sandboxed generator scripts."""
import io
import os
import shutil
import tarfile
import threading
import zipfile

from flask import current_app
from werkzeug.utils import secure_filename

SCRIPT_NAME = "generate.py"
# generate.py runs in flagprint/generator (Python plus C, Rust and binary tools for rev/pwn builds, see
# generator/Dockerfile). Plain Python is the fallback if it hasn't been built on this server.
SANDBOX_IMAGE = os.environ.get("FLAGPRINT_SANDBOX_IMAGE", "flagprint/generator:latest")
FALLBACK_IMAGE = "python:3.12-slim"
SANDBOX_TIMEOUT = 180
SANDBOX_MEMORY = "1g"
TOOL_HINT = ("The script needs a tool the sandbox doesn't have. Build the full sandbox on the server: "
             "docker build -t flagprint/generator:latest CTFd/plugins/flagprint/generator")
MAX_SOURCE_SIZE = 200 * 1024 * 1024

_locks = {}
_locks_guard = threading.Lock()


MAX_FORM_UPLOAD = 100 * 1024 * 1024  # files sent with the challenge form (base64 in JSON)


class GenerationError(Exception):
    pass


def safe_name(name):
    return secure_filename(name or "")


def decode_upload(value):
    """A form upload is {"name": ..., "data": base64}. Returns (name, bytes) or None."""
    import base64
    import binascii

    if not value:
        return None
    if isinstance(value, str):
        import json
        try:
            value = json.loads(value)
        except ValueError:
            raise GenerationError("An uploaded file could not be read. Choose it again.")
    if not isinstance(value, dict) or not value.get("name") or "data" not in value:
        return None
    try:
        data = base64.b64decode(value["data"], validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise GenerationError(f"{value.get('name')} could not be read. Choose it again.")
    if len(data) > MAX_FORM_UPLOAD:
        raise GenerationError(f"{value['name']} is larger than 100 MB.")
    return value["name"], data


def _root():
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "flagprint")


def challenge_dir(challenge_id):
    return os.path.join(_root(), str(int(challenge_id)))


def source_dir(challenge_id):
    return os.path.join(challenge_dir(challenge_id), "source")


def source_path(challenge):
    return os.path.join(source_dir(challenge.id), challenge.filename) if challenge.filename else None


def script_path(challenge_id):
    return os.path.join(source_dir(challenge_id), SCRIPT_NAME)


def account_path(challenge, account_id):
    return os.path.join(challenge_dir(challenge.id), "issued", str(int(account_id)), challenge.filename)


def _clear_source_files(challenge_id):
    folder = source_dir(challenge_id)
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name)
        if name != SCRIPT_NAME and os.path.isfile(path):
            os.remove(path)


def save_source_bytes(challenge_id, filename, data):
    """Replace mode: the file that contains the sample flag."""
    filename = secure_filename(filename or "")
    if not filename or filename == SCRIPT_NAME:
        raise GenerationError("Give the file a normal name, such as challenge.zip.")
    os.makedirs(source_dir(challenge_id), exist_ok=True)
    _clear_source_files(challenge_id)
    with open(os.path.join(source_dir(challenge_id), filename), "wb") as handle:
        handle.write(data)
    clear_issued(challenge_id)
    return filename


def save_script_bytes(challenge_id, data):
    os.makedirs(source_dir(challenge_id), exist_ok=True)
    with open(script_path(challenge_id), "wb") as handle:
        handle.write(data)
    clear_issued(challenge_id)


def input_dir(challenge_id):
    return os.path.join(source_dir(challenge_id), "input")


def input_file(challenge_id):
    """Script mode: (name, path) of the optional input file, or None."""
    folder = input_dir(challenge_id)
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    return (names[0], os.path.join(folder, names[0])) if names else None


def save_input_bytes(challenge_id, filename, data):
    filename = secure_filename(filename or "")
    if not filename:
        raise GenerationError("Give the input file a normal name, such as cover.png.")
    shutil.rmtree(input_dir(challenge_id), ignore_errors=True)
    os.makedirs(input_dir(challenge_id), exist_ok=True)
    with open(os.path.join(input_dir(challenge_id), filename), "wb") as handle:
        handle.write(data)
    clear_issued(challenge_id)
    return filename


def remove_input(challenge_id):
    shutil.rmtree(input_dir(challenge_id), ignore_errors=True)
    clear_issued(challenge_id)


def read_bytes(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()


def clear_account(challenge_id, account_id):
    """Drop one account's generated copy so its next download carries its current flag."""
    shutil.rmtree(os.path.join(challenge_dir(challenge_id), "issued", str(int(account_id))), ignore_errors=True)


def clear_issued(challenge_id):
    shutil.rmtree(os.path.join(challenge_dir(challenge_id), "issued"), ignore_errors=True)


def delete_all(challenge_id):
    shutil.rmtree(challenge_dir(challenge_id), ignore_errors=True)


def count_sample(data, sample):
    """How many times the sample flag appears in a file's bytes (zip members included)."""
    if data is None:
        return 0
    needle = sample.encode()
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return sum(archive.read(info).count(needle) for info in archive.infolist() if not info.is_dir())
    return data.count(needle)


def sample_occurrences(challenge):
    return count_sample(read_bytes(source_path(challenge)), challenge.sample_flag)


def _replace(challenge, flag):
    sample = challenge.sample_flag.encode()
    path = source_path(challenge)
    if zipfile.is_zipfile(path):
        output = io.BytesIO()
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                data = b"" if info.is_dir() else source.read(info).replace(sample, flag.encode())
                target.writestr(info, data)
        return output.getvalue()
    with open(path, "rb") as handle:
        data = handle.read()
    if sample not in data:
        raise GenerationError("The sample flag was not found in the uploaded file.")
    return data.replace(sample, flag.encode())


def _tar_of(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def run_script(script, output_name, flag, input_item=None, label="test"):
    """Run a generate.py in a locked-down container and return the file it wrote.

    `script` is the script's bytes, `input_item` an optional (name, bytes) input file."""
    try:
        import docker
    except ImportError:
        raise GenerationError("Script mode needs the Python docker package on the CTFd server: pip install docker")

    files = {"work/" + SCRIPT_NAME: script}
    if input_item:
        files["work/input/" + input_item[0]] = input_item[1]
    try:
        client = docker.from_env()
        image = SANDBOX_IMAGE
        try:
            client.images.get(SANDBOX_IMAGE)
        except docker.errors.ImageNotFound:
            image = FALLBACK_IMAGE
            try:
                client.images.get(FALLBACK_IMAGE)
            except docker.errors.ImageNotFound:
                client.images.pull(FALLBACK_IMAGE)
    except docker.errors.DockerException as error:
        raise GenerationError(f"Docker is needed to run generate.py and is not reachable: {error}") from error
    container = client.containers.create(
        image,
        command=["sh", "-c", "mkdir -p /work/out && cd /work && python generate.py"],
        environment={
            "FLAG": flag,
            "INPUT": f"/work/input/{input_item[0]}" if input_item else "",
            "OUTPUT_DIR": "/work/out",
            "OUTPUT_NAME": output_name or "",
        },
        network_disabled=True,
        mem_limit=SANDBOX_MEMORY,
        memswap_limit=SANDBOX_MEMORY,
        pids_limit=256,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        labels={"flagprint.challenge_id": str(label)},
    )
    try:
        container.put_archive("/", _tar_of(files))
        container.start()
        try:
            result = container.wait(timeout=SANDBOX_TIMEOUT)
        except Exception as error:
            raise GenerationError(f"generate.py did not finish within {SANDBOX_TIMEOUT}s.") from error
        if result.get("StatusCode") != 0:
            logs = container.logs(tail=20).decode(errors="replace").strip()
            missing = "No such file or directory" in logs and image == FALLBACK_IMAGE
            raise GenerationError(f"generate.py failed:\n{logs}" + (f"\n\n{TOOL_HINT}" if missing else ""))
        stream, _ = container.get_archive("/work/out")
        with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as archive:
            produced = [m for m in archive.getmembers() if m.isfile()]
            if not produced:
                raise GenerationError("generate.py ran but did not write a file into OUTPUT_DIR.")
            return archive.extractfile(produced[0]).read()
    finally:
        container.remove(force=True)


def _run_script(challenge, flag):
    script = read_bytes(script_path(challenge.id))
    if script is None:
        raise GenerationError("No generate.py uploaded for this challenge.")
    found = input_file(challenge.id)
    item = (found[0], read_bytes(found[1])) if found else None
    return run_script(script, challenge.filename, flag, item, label=challenge.id)


def _lock_for(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def issued_file(challenge, account_id, flag):
    """Path of this account's copy, generating it on first request."""
    path = account_path(challenge, account_id)
    if os.path.exists(path):
        return path
    with _lock_for((challenge.id, account_id)):
        if os.path.exists(path):
            return path
        if challenge.delivery == "replace":
            data = _replace(challenge, flag)
        elif challenge.delivery == "script":
            data = _run_script(challenge, flag)
        else:
            raise GenerationError("This challenge has no per-team file.")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    return path
