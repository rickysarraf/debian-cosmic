#!/usr/bin/env python3
"""Fail-closed package-pair provenance and immutable OCI promotion (stdlib only)."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/build-packages.yml"
RECIPE = ".github/workflows/package-build.yml"
PACKAGES = ("cosmic-epoch", "cosmic-utils")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
NUMBER = re.compile(r"[1-9][0-9]*")
MAX_DEB_SIZE = 8 * 1024**3
MAX_METADATA_SIZE = 65536
MAX_PROVENANCE_ARCHIVE_SIZE = 131072
RUNNER_KEYS = ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def api(path):
    return json.loads(command(["gh", "api", path], capture_output=True).stdout)


def notice(message):
    # Do not allow untrusted API data to emit workflow commands or extra lines.
    print("Package reuse: " + str(message).replace("\r", " ").replace("\n", " "), flush=True)


def numeric(value):
    value = str(value)
    if not NUMBER.fullmatch(value):
        raise ValueError("invalid run identity")
    return value


def global_and_caller_settings(text):
    """Select literal YAML blocks without a YAML dependency; reject ambiguity.

    All build commands live in the fully hashed reusable recipe. In this caller
    only global env/defaults/permissions and the complete build job affect them.
    Anchors, tags, flow-style jobs and unfamiliar top-level keys fail closed.
    """
    if re.search(r"(^|\s)[&*!][A-Za-z_]", text) or "<<:" in text:
        raise ValueError("workflow anchors/tags/merges are not supported")
    lines = text.splitlines(keepends=True)
    tops = [(i, re.fullmatch(r"([a-z][a-z_-]*):[^\n]*\n?", line))
            for i, line in enumerate(lines) if line and not line[0].isspace()
            and not line.startswith("#")]
    if any(match is None for _, match in tops):
        raise ValueError("ambiguous workflow top-level syntax")
    keys = [match[1] for _, match in tops]
    if len(keys) != len(set(keys)) or set(keys) - {
        "name", "on", "concurrency", "env", "defaults", "permissions", "jobs",
        "run-name",
    }:
        raise ValueError("duplicate or unsupported workflow settings")
    if not {"env", "jobs"}.issubset(keys):
        raise ValueError("missing workflow settings")
    blocks = {}
    for position, (start, match) in enumerate(tops):
        end = tops[position + 1][0] if position + 1 < len(tops) else len(lines)
        blocks[match[1]] = "".join(lines[start:end]).rstrip()
    jobs = blocks["jobs"].splitlines(keepends=True)
    if jobs[0].strip() != "jobs:":
        raise ValueError("flow-style jobs are not supported")
    boundaries = [(i, re.fullmatch(r"  ([a-z][a-z0-9_-]*):\s*\n?", line))
                  for i, line in enumerate(jobs)
                  if line.startswith("  ") and len(line) > 2
                  and not line[2].isspace() and not line[2] == "#"]
    if any(match is None for _, match in boundaries):
        raise ValueError("ambiguous job syntax")
    names = [match[1] for _, match in boundaries]
    if len(names) != len(set(names)) or names.count("build-and-push") != 1:
        raise ValueError("missing or duplicate build caller")
    position = names.index("build-and-push")
    start = boundaries[position][0]
    end = boundaries[position + 1][0] if position + 1 < len(boundaries) else len(jobs)
    caller = "".join(jobs[start:end]).rstrip()
    if caller.count("    uses: ./.github/workflows/package-build.yml") != 1:
        raise ValueError("build caller no longer uses the fingerprinted recipe")
    return {key: blocks.get(key, "") for key in ("env", "defaults", "permissions")} | {
        "caller": caller,
    }


def fingerprint(allow_unverified=False):
    trees = command(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "HEAD", "--", "images", "packaging"],
        capture_output=True,
    ).stdout.decode()
    if not trees or "\timages/" not in trees or "\tpackaging/" not in trees:
        raise ValueError("missing committed build contexts")
    workflow_text = (ROOT / WORKFLOW).read_text()
    try:
        settings = global_and_caller_settings(workflow_text)
    except ValueError:
        if not allow_unverified:
            raise
        # A fresh pair can still be bound to this entire workflow. The strict
        # resolver will never reuse such a pair while its settings are uncertain.
        settings = {"unverified_workflow": workflow_text}
        print("Package reuse: uncertain workflow settings; fresh-build provenance only", file=sys.stderr)
    inputs = {
        "trees": trees,
        "settings": settings,
        "recipe": (ROOT / RECIPE).read_text(),
        "resolver": Path(__file__).read_text(),
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def validate_builder_runner(runner):
    # The recipe builds amd64 packages on ubuntu-latest; image rollouts can
    # allocate different versions to each matrix leg and the release job.
    if (not isinstance(runner, dict) or set(runner) != set(RUNNER_KEYS)
            or any(not isinstance(value, str) for value in runner.values())
            or runner["RUNNER_OS"] != "Linux" or runner["RUNNER_ARCH"] != "X64"
            or not re.fullmatch(r"ubuntu[0-9]{2}", runner["ImageOS"])
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", runner["ImageVersion"])):
        raise ValueError("missing/invalid builder runner provenance or platform")


def runner_environment():
    runner = {key: os.environ.get(key, "") for key in RUNNER_KEYS}
    validate_builder_runner(runner)
    return runner


def configuration():
    repo = os.environ["GITHUB_REPOSITORY"]
    prefix = os.environ["IMAGE_PREFIX"].lower()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid repository")
    if os.environ["REGISTRY"] != "ghcr.io" or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", prefix):
        raise ValueError("unsupported registry or image namespace")
    base = os.environ["BASE_VERSION"]
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+~:-]*", base):
        raise ValueError("invalid base version")
    return repo, f"ghcr.io/{prefix}", base


def run_details(run_id):
    repo, _, _ = configuration()
    return api(f"repos/{repo}/actions/runs/{numeric(run_id)}")


def identity(run):
    repo, _, base = configuration()
    return {
        "repository": repo,
        "run_id": numeric(run["id"]),
        "attempt": numeric(run["run_attempt"]),
        "run_number": numeric(run["run_number"]),
        "head_sha": run["head_sha"],
        "workflow_id": numeric(run["workflow_id"]),
        "base_version": base,
    }


def trusted(run, workflow_id, current=False):
    repo, _, _ = configuration()
    if (run["repository"]["full_name"] != repo
            or run["head_repository"]["full_name"] != repo
            or str(run["workflow_id"]) != str(workflow_id)
            or run["head_branch"] != "main"
            or run["event"] not in ("push", "schedule", "workflow_dispatch")):
        raise ValueError("not a same-repository main build of this workflow")
    if current:
        if numeric(run["id"]) != numeric(os.environ["GITHUB_RUN_ID"]):
            raise ValueError("not the current build")
        if numeric(run["run_attempt"]) != numeric(os.environ["GITHUB_RUN_ATTEMPT"]):
            raise ValueError("current run attempt changed")
        if run["status"] != "in_progress":
            raise ValueError("current run is no longer in progress")
    elif run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("source run is not completed successfully")


def image_reference(package):
    _, namespace, _ = configuration()
    return f"{namespace}/debian-{package}"


def registry_digest(reference):
    result = command(
        ["docker", "buildx", "imagetools", "inspect", reference,
         "--format", "{{json .Manifest}}"],
        capture_output=True,
    )
    digest = json.loads(result.stdout)["digest"]
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError("invalid registry manifest digest")
    return digest


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deb_headers(path):
    fields = {}
    for field in ("Package", "Version", "Architecture"):
        fields[field] = command(
            ["dpkg-deb", "--field", str(path), field], capture_output=True,
        ).stdout.decode().strip()
    return fields


def screen_metadata(metadata, package, run, expected_fingerprint):
    expected_identity = identity(run)
    version = f'{expected_identity["base_version"]}.build{expected_identity["run_number"]}'
    if (type(metadata.get("schema")) is not int or metadata["schema"] != 2
            or metadata.get("identity") != expected_identity
            or metadata.get("fingerprint") != expected_fingerprint):
        raise ValueError("missing/mismatched provenance, base version or build inputs")
    builder_runner = metadata.get("builder_runner")
    validate_builder_runner(builder_runner)
    if (expected_identity["run_id"] != numeric(os.environ["GITHUB_RUN_ID"])
            and builder_runner != runner_environment()):
        raise ValueError("builder runner environment does not match reuse runner")
    deb = metadata["deb"]
    if (deb["filename"] != f"{package}-monorepo.deb"
            or deb["package"] != f"{package}-monorepo"
            or deb["version"] != version or deb["architecture"] != "amd64"):
        raise ValueError("package metadata does not match source run version/architecture")
    if (type(deb["size"]) is not int or not 0 < deb["size"] <= MAX_DEB_SIZE
            or not isinstance(deb["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", deb["sha256"])):
        raise ValueError("invalid package size or SHA256 provenance")
    image = metadata["image"]
    reference = image_reference(package)
    tag = f'{reference}:run-{expected_identity["run_id"]}-attempt-{expected_identity["attempt"]}'
    if (image["repository"] != reference or image["tag"] != tag
            or not isinstance(image["digest"], str) or not DIGEST.fullmatch(image["digest"])):
        raise ValueError("invalid immutable image provenance")
    return f'{reference}@{image["digest"]}'


def validate_metadata(metadata, package, run, expected_fingerprint, path):
    immutable = screen_metadata(metadata, package, run, expected_fingerprint)
    deb = metadata["deb"]
    if path.stat().st_size != deb["size"] or sha256(path) != deb["sha256"]:
        raise ValueError("package size or SHA256 mismatch")
    if deb_headers(path) != {
        "Package": deb["package"], "Version": deb["version"], "Architecture": "amd64",
    }:
        raise ValueError("actual downloaded .deb headers do not match provenance")
    image = metadata["image"]
    if registry_digest(immutable) != image["digest"]:
        raise ValueError("preserved registry image is unavailable or mismatched")
    return immutable


def artifact_pair(run_id):
    repo, _, _ = configuration()
    response = api(f"repos/{repo}/actions/runs/{numeric(run_id)}/artifacts?per_page=100")
    artifacts = response["artifacts"]
    if response["total_count"] != len(artifacts):
        raise ValueError("artifact listing is incomplete")
    pair = {}
    for package in PACKAGES:
        pair[package] = {}
        for kind in ("deb", "provenance"):
            matches = [a for a in artifacts if a["name"] == f"{package}-{kind}"]
            if len(matches) != 1 or matches[0]["expired"]:
                raise ValueError(f"{package}-{kind}: artifact missing, duplicate or expired")
            if kind == "provenance" and not (
                type(matches[0]["size_in_bytes"]) is int
                and 0 < matches[0]["size_in_bytes"] <= MAX_PROVENANCE_ARCHIVE_SIZE
            ):
                raise ValueError("provenance artifact is not lightweight")
            pair[package][kind] = numeric(matches[0]["id"])
    return pair


def download_artifact(artifact_id, package, destination, *, provenance_only=False):
    repo, _, _ = configuration()
    destination.mkdir(parents=True, exist_ok=False)
    archive_path = destination / "artifact.zip"
    try:
        with archive_path.open("wb") as stream:
            command(["gh", "api", f"repos/{repo}/actions/artifacts/{numeric(artifact_id)}/zip"],
                    stdout=stream)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            expected = {"metadata.json"}
            if not provenance_only:
                expected.add(f"{package}-monorepo.deb")
            if len(members) != len(expected) or {member.filename for member in members} != expected:
                raise ValueError("artifact does not contain exactly the expected files")
            for member in members:
                limit = MAX_METADATA_SIZE if member.filename == "metadata.json" else MAX_DEB_SIZE
                if not 0 < member.file_size <= limit:
                    raise ValueError("invalid artifact member size")
                # Never extract paths, permissions, symlinks or executable files.
                with archive.open(member) as source, (destination / member.filename).open("wb") as target:
                    shutil.copyfileobj(source, target)
        return json.loads((destination / "metadata.json").read_text())
    finally:
        archive_path.unlink(missing_ok=True)


def download_provenance(artifact_id, package, destination):
    return download_artifact(artifact_id, package, destination, provenance_only=True)


def scratch():
    # Builds/downloads are large; never place these in /tmp or the source checkout.
    return Path.home() / "NoBackup/GEMINI_SCRATCH" / (
        f'package-reuse-{numeric(os.environ["GITHUB_RUN_ID"])}-'
        f'{numeric(os.environ["GITHUB_RUN_ATTEMPT"])}'
    )


def verify_pair(run, expected_fingerprint, destination):
    artifacts = artifact_pair(run["id"])
    verified = {}
    def recheck():
        again = run_details(run["id"])
        if identity(again) != identity(run) or artifact_pair(run["id"]) != artifacts:
            raise ValueError("source run attempt or artifact identity changed during validation")
        trusted(again, run["workflow_id"],
                current=numeric(run["id"]) == numeric(os.environ["GITHUB_RUN_ID"]))
        return again

    try:
        screened = {}
        for package in PACKAGES:
            metadata = download_provenance(
                artifacts[package]["provenance"], package, destination / f"{package}-provenance",
            )
            screen_metadata(metadata, package, run, expected_fingerprint)
            screened[package] = metadata
        # Neither large package is downloaded until both lightweight records pass.
        recheck()
        for package in PACKAGES:
            directory = destination / package
            metadata = download_artifact(artifacts[package]["deb"], package, directory)
            if metadata != screened[package]:
                raise ValueError("package provenance does not match screened metadata")
            path = directory / f"{package}-monorepo.deb"
            immutable = validate_metadata(metadata, package, run, expected_fingerprint, path)
            verified[package] = (path, metadata, immutable)
        # Recheck after downloads: a rerun/cancellation/expiration must not race selection.
        again = recheck()
        return verified, again
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def output(values, variable="GITHUB_OUTPUT"):
    with Path(os.environ[variable]).open("a") as stream:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError("invalid workflow output")
            stream.write(f"{key}={value}\n")


def resolve():
    output({"run_id": "", "attempt": ""})
    if os.environ["GITHUB_EVENT_NAME"] != "push" or os.environ["GITHUB_REF"] != "refs/heads/main":
        notice("fresh schedule/dispatch or path-gated PR/wip run; reuse disabled")
        return
    directory = scratch() / "selection"
    try:
        inputs = fingerprint()
        current = run_details(os.environ["GITHUB_RUN_ID"])
        workflow_id = current["workflow_id"]
        repo, _, _ = configuration()
        # Bounded search: not finding an older pair is safe (build both).
        runs = api(
            f"repos/{repo}/actions/workflows/{numeric(workflow_id)}/runs"
            "?branch=main&status=success&per_page=100"
        )["workflow_runs"]
        for candidate in runs:
            run_id = numeric(candidate["id"])
            if run_id == os.environ["GITHUB_RUN_ID"]:
                continue
            try:
                run = run_details(run_id)
                trusted(run, workflow_id)
                verified, again = verify_pair(run, inputs, directory)
                trusted(again, workflow_id)
                output({"run_id": run_id, "attempt": numeric(run["run_attempt"])})
                notice(f"accepted run {run_id}: complete pair, matching inputs/headers/hashes and preserved OCI digests")
                return
            except Exception as error:
                notice(f"rejected run {run_id}: {error}")
            finally:
                shutil.rmtree(directory, ignore_errors=True)
        notice("no compatible trusted complete pair; rebuilding both packages")
    except Exception as error:
        notice(f"cannot verify compatibility ({error}); rebuilding both packages")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def record():
    package = os.environ["PACKAGE_NAME"]
    if package not in PACKAGES:
        raise ValueError("unexpected package")
    builder_runner = runner_environment()
    run = run_details(os.environ["GITHUB_RUN_ID"])
    trusted(run, run["workflow_id"], current=True)
    directory = Path(os.environ["DIST_DIR"])
    path = directory / f"{package}-monorepo.deb"
    if list(directory.glob("*.deb")) != [path]:
        raise ValueError("build did not produce exactly one expected package")
    headers = deb_headers(path)
    build_identity = identity(run)
    if headers != {
        "Package": f"{package}-monorepo",
        "Version": f'{build_identity["base_version"]}.build{build_identity["run_number"]}',
        "Architecture": "amd64",
    }:
        raise ValueError("built package does not match run version/architecture")
    reference = image_reference(package)
    tag = f'{reference}:run-{build_identity["run_id"]}-attempt-{build_identity["attempt"]}'
    # Bind to the digest returned by this push, not a subsequent mutable tag lookup.
    push_log = command(["docker", "push", tag], capture_output=True).stdout.decode()
    digests = re.findall(
        r"(?m)^[^\r\n]*digest: (sha256:[0-9a-f]{64}) size: [0-9]+\s*$", push_log,
    )
    if len(digests) != 1:
        raise ValueError("push did not return an immutable manifest digest")
    pushed_digest = digests[0]
    if registry_digest(f"{reference}@{pushed_digest}") != pushed_digest:
        raise ValueError("pushed immutable image cannot be verified")
    metadata = {
        "schema": 2,
        "identity": build_identity,
        "fingerprint": (directory / "fingerprint").read_text().strip(),
        "builder_runner": builder_runner,
        "deb": {
            "filename": path.name, "package": headers["Package"],
            "version": headers["Version"], "architecture": headers["Architecture"],
            "size": path.stat().st_size, "sha256": sha256(path),
        },
        "image": {"repository": reference, "tag": tag, "digest": pushed_digest},
    }
    if not re.fullmatch(r"[0-9a-f]{64}", metadata["fingerprint"]):
        raise ValueError("invalid build fingerprint")
    (directory / "metadata.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
    notice(f"recorded {package} package SHA256 and immutable OCI source {tag}")


def release():
    source_id = os.environ.get("SOURCE_RUN_ID") or os.environ["GITHUB_RUN_ID"]
    source_attempt = os.environ.get("SOURCE_ATTEMPT") or os.environ["GITHUB_RUN_ATTEMPT"]
    current = run_details(os.environ["GITHUB_RUN_ID"])
    run = run_details(source_id)
    is_current = numeric(source_id) == numeric(os.environ["GITHUB_RUN_ID"])
    trusted(run, current["workflow_id"], current=is_current)
    if numeric(source_attempt) != numeric(run["run_attempt"]):
        raise ValueError("selected source run attempt changed")
    directory = scratch() / "release"
    if directory.exists():
        raise ValueError("release destination is not clean")
    try:
        verified, again = verify_pair(run, fingerprint(allow_unverified=is_current), directory / "source")
        trusted(again, current["workflow_id"], current=is_current)
        dist = directory / "dist"
        dist.mkdir()
        for package, (path, metadata, immutable) in verified.items():
            version = metadata["deb"]["version"].replace(":", "_")
            shutil.copyfile(path, dist / f"{package}-monorepo_{version}_amd64.deb")
        # No tag is promoted until both exact source packages/images are verified.
        for package, (_, metadata, immutable) in verified.items():
            command(["docker", "buildx", "imagetools", "create", "--prefer-index=false",
                     "--tag", image_reference(package) + ":latest", immutable])
            if registry_digest(image_reference(package) + ":latest") != metadata["image"]["digest"]:
                raise ValueError("promoted latest digest does not match the selected package image")
        output({
            "release_version": verified["cosmic-epoch"][1]["deb"]["version"],
            "source_run_id": numeric(source_id),
            "epoch_image": verified["cosmic-epoch"][2],
            "utils_image": verified["cosmic-utils"][2],
        })
        output({"DIST_DIR": str(dist), "APT_REPO_DIR": str(directory / "repo")}, "GITHUB_ENV")
        notice(f"release uses only run {source_id}, attempt {source_attempt}; exact OCI digests promoted")
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"fingerprint", "resolve", "record", "release"}:
            raise ValueError("usage: package_reuse.py fingerprint|resolve|record|release")
        if sys.argv[1] == "fingerprint":
            print(fingerprint(allow_unverified=True))
        else:
            globals()[sys.argv[1]]()
    except Exception as error:
        notice(f"fatal validation failure: {error}")
        sys.exit(1)
