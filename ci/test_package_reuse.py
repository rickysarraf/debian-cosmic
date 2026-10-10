"""Small stdlib-only validation suite; no host package builds or fixture writes."""

import io
import json
import os
from pathlib import Path
import subprocess
import textwrap
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from ci import package_reuse as reuse


ENV = {
    "GITHUB_REPOSITORY": "owner/project", "IMAGE_PREFIX": "owner",
    "REGISTRY": "ghcr.io", "BASE_VERSION": "1.10.0-1",
    "GITHUB_RUN_ID": "200", "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_RUN_NUMBER": "20", "GITHUB_REF": "refs/heads/main",
    "GITHUB_EVENT_NAME": "push",
}
RUN = {
    "id": 100, "run_attempt": 1, "run_number": 10, "head_sha": "a" * 40,
    "workflow_id": 7, "repository": {"full_name": "owner/project"},
    "head_repository": {"full_name": "owner/project"}, "head_branch": "main",
    "event": "push", "status": "completed", "conclusion": "success",
}
DIGEST = "sha256:" + "c" * 64


def metadata(package="cosmic-epoch"):
    return {
        "schema": 1, "identity": reuse.identity(RUN), "fingerprint": "f" * 64,
        "deb": {
            "filename": f"{package}-monorepo.deb", "package": f"{package}-monorepo",
            "version": "1.10.0-1.build10", "architecture": "amd64",
            "size": 12, "sha256": "d" * 64,
        },
        "image": {
            "repository": f"ghcr.io/owner/debian-{package}",
            "tag": f"ghcr.io/owner/debian-{package}:run-100-attempt-1",
            "digest": DIGEST,
        },
    }


def artifact_ids():
    return {
        package: {"deb": str(i + 1), "provenance": str(i + 3)}
        for i, package in enumerate(reuse.PACKAGES)
    }


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_real_fingerprint_is_stable_and_covers_build_files(self):
        self.assertEqual(reuse.fingerprint(), reuse.fingerprint())
        self.assertRegex(reuse.fingerprint(), r"^[0-9a-f]{64}$")
        original = reuse.fingerprint()
        for variable in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion"):
            with patch.dict(os.environ, {variable: "changed-setting"}):
                self.assertNotEqual(original, reuse.fingerprint())
        original_read = Path.read_text
        for target in (reuse.ROOT / reuse.RECIPE, Path(reuse.__file__)):
            def changed_read(path, *args, **kwargs):
                return original_read(path, *args, **kwargs) + ("# changed build input" if path == target else "")
            with patch.object(Path, "read_text", changed_read):
                self.assertNotEqual(original, reuse.fingerprint())
        tree_result = subprocess.CompletedProcess([], 0, stdout=b"100644 blob changed\timages/Dockerfile\n100644 blob x\tpackaging/control\n")
        with patch.object(reuse, "command", return_value=tree_result):
            self.assertNotEqual(original, reuse.fingerprint())
        with patch.object(reuse.Path, "read_text", return_value="changed"):
            with self.assertRaises(ValueError):
                reuse.fingerprint()

    def test_caller_projection_ignores_only_orchestration(self):
        text = (reuse.ROOT / reuse.WORKFLOW).read_text()
        baseline = reuse.global_and_caller_settings(text)
        modified = text.replace("python3 ci/package_reuse.py resolve", "echo resolver-only")
        self.assertEqual(baseline, reuse.global_and_caller_settings(modified))
        for old, new in (
            ('BASE_VERSION: "1.10.0-1"', 'BASE_VERSION: "2.0-1"'),
            ('base_version: "1.10.0-1"', 'base_version: "2.0-1"'),
            ("registry: ghcr.io", "registry: other.io"),
            ("secrets: inherit", "secrets: {}"),
        ):
            with self.subTest(old=old):
                self.assertNotEqual(baseline, reuse.global_and_caller_settings(text.replace(old, new)))
        self.assertNotEqual(
            baseline, reuse.global_and_caller_settings(text.replace("jobs:", "defaults:\n  run:\n    shell: bash\n\njobs:", 1)),
        )

    def test_projection_fails_closed_on_uncertain_yaml(self):
        text = (reuse.ROOT / reuse.WORKFLOW).read_text()
        for change in (
            "env: &settings", "env: {REGISTRY: ghcr.io}\nenv:",
            "env: !custom", "unexpected:\n  value: 1\nenv:",
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                reuse.global_and_caller_settings(text.replace("env:", change, 1))
        with self.assertRaises(ValueError):
            reuse.global_and_caller_settings(text.replace("jobs:", "jobs: {}", 1))
        with self.assertRaises(ValueError):
            reuse.global_and_caller_settings(text.replace("package-build.yml", "other-build.yml"))

    def test_uncertain_settings_disable_reuse_but_allow_fresh_provenance(self):
        with patch.object(reuse, "global_and_caller_settings", side_effect=ValueError("unsupported")):
            with self.assertRaises(ValueError):
                reuse.fingerprint()
            self.assertRegex(reuse.fingerprint(allow_unverified=True), r"^[0-9a-f]{64}$")

    def test_real_build_gate_preserves_wip_paths_and_fresh_main_fallback(self):
        recipe = (reuse.ROOT / reuse.RECIPE).read_text()
        gate = textwrap.dedent(recipe.split("        run: |\n", 1)[1].split(
            "      - name: Checkout repository", 1,
        )[0]).replace(' >> "$GITHUB_OUTPUT"', "")
        for event, ref, source, package, epoch, utils, expected in (
            ("push", "refs/heads/main", "", "cosmic-epoch", "false", "false", "true"),
            ("push", "refs/heads/main", "100", "cosmic-utils", "true", "true", "false"),
            ("push", "refs/heads/wip/test", "", "cosmic-epoch", "false", "true", "false"),
            ("push", "refs/heads/wip/test", "", "cosmic-utils", "false", "true", "true"),
            ("pull_request", "refs/pull/1/merge", "", "cosmic-epoch", "true", "false", "true"),
            ("schedule", "refs/heads/main", "100", "cosmic-epoch", "false", "false", "true"),
            ("workflow_dispatch", "refs/heads/main", "100", "cosmic-utils", "false", "false", "true"),
        ):
            env = os.environ | {
                "GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "REUSE_RUN_ID": source,
                "PACKAGE_NAME": package, "EPOCH_CHANGED": epoch, "UTILS_CHANGED": utils,
            }
            result = subprocess.run(["bash"], input=gate, text=True, capture_output=True, env=env, check=True)
            with self.subTest(event=event, ref=ref, package=package):
                self.assertEqual(result.stdout.strip(), f"should_build={expected}")

    def test_trust_requires_successful_same_workflow_repository_main(self):
        reuse.trusted(RUN, 7)
        for field, value in (
            ("workflow_id", 8), ("head_branch", "wip/test"), ("event", "pull_request"),
            ("status", "in_progress"), ("conclusion", "failure"),
            ("repository", {"full_name": "other/project"}),
            ("head_repository", {"full_name": "fork/project"}),
        ):
            run = RUN | {field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                reuse.trusted(run, 7)

    def test_current_run_trust_requires_current_attempt_and_live_run(self):
        run = RUN | {"id": 200, "status": "in_progress", "conclusion": None}
        reuse.trusted(run, 7, current=True)
        for update in ({"id": 100}, {"run_attempt": 2}, {"status": "completed"}):
            with self.assertRaises(ValueError):
                reuse.trusted(run | update, 7, current=True)

    def validate(self, record, *, headers=None, digest=DIGEST, sha="d" * 64):
        path = MagicMock(spec=Path)
        path.stat.return_value.st_size = 12
        if headers is None:
            headers = {"Package": "cosmic-epoch-monorepo", "Version": "1.10.0-1.build10",
                       "Architecture": "amd64"}
        with patch.object(reuse, "sha256", return_value=sha), \
                patch.object(reuse, "deb_headers", return_value=headers), \
                patch.object(reuse, "registry_digest", return_value=digest):
            return reuse.validate_metadata(record, "cosmic-epoch", RUN, "f" * 64, path)

    def test_valid_pair_member_checks_hash_headers_version_and_digest(self):
        self.assertEqual(self.validate(metadata()), "ghcr.io/owner/debian-cosmic-epoch@" + DIGEST)
        for section, field, value in (
            ("identity", "attempt", "2"), ("identity", "base_version", "2.0-1"),
            ("deb", "version", "1.10.0-1.build9"), ("deb", "architecture", "arm64"),
            ("deb", "filename", "../escape.deb"), ("deb", "size", 99),
            ("image", "tag", "ghcr.io/owner/debian-cosmic-epoch:latest"),
            ("image", "repository", "ghcr.io/fork/debian-cosmic-epoch"),
            ("image", "digest", DIGEST + "\nrun_id=999"),
        ):
            record = metadata()
            record[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(record)
        for update in ({"schema": 0}, {"fingerprint": "other"}, {"identity": {}}):
            with self.assertRaises(ValueError):
                self.validate(metadata() | update)
        for header in (
            {"Package": "malicious", "Version": "1.10.0-1.build10", "Architecture": "amd64"},
            {"Package": "cosmic-epoch-monorepo", "Version": "1.10.0-1.build9", "Architecture": "amd64"},
        ):
            with self.assertRaises(ValueError):
                self.validate(metadata(), headers=header)
        with self.assertRaises(ValueError):
            self.validate(metadata(), sha="wrong")
        with self.assertRaises(ValueError):
            self.validate(metadata(), digest="sha256:" + "e" * 64)

    def test_missing_expired_duplicate_and_incomplete_artifacts_rejected(self):
        artifacts = [
            {"name": f"{package}-{kind}", "id": i + offset, "expired": False,
             "size_in_bytes": 1024}
            for kind, offset in (("deb", 1), ("provenance", 3))
            for i, package in enumerate(reuse.PACKAGES)
        ]
        with patch.object(reuse, "api", return_value={"total_count": 4, "artifacts": artifacts}):
            self.assertEqual(reuse.artifact_pair(100), artifact_ids())
        for response in (
            {"total_count": 0, "artifacts": []},
            {"total_count": 4, "artifacts": artifacts[:3] + [artifacts[3] | {"expired": True}]},
            {"total_count": 5, "artifacts": artifacts + [artifacts[0]]},
            {"total_count": 5, "artifacts": artifacts + [artifacts[2]]},
            {"total_count": 2, "artifacts": artifacts[:2]},
            {"total_count": 4, "artifacts": artifacts[:3] + [
                artifacts[3] | {"size_in_bytes": reuse.MAX_PROVENANCE_ARCHIVE_SIZE + 1},
            ]},
            {"total_count": 101, "artifacts": artifacts},
        ):
            with patch.object(reuse, "api", return_value=response), self.assertRaises(ValueError):
                reuse.artifact_pair(100)

    def test_pair_validates_both_members_from_same_run(self):
        records = {package: metadata(package) for package in reuse.PACKAGES}
        events = []
        def provenance(_, package, dest):
            events.append(("provenance", package))
            return records[package]
        def screening(record, package, *args):
            events.append(("screen", package))
            return reuse.image_reference(package) + "@" + DIGEST
        def download(_, package, dest):
            self.assertEqual(events[:4], [
                ("provenance", "cosmic-epoch"), ("screen", "cosmic-epoch"),
                ("provenance", "cosmic-utils"), ("screen", "cosmic-utils"),
            ])
            events.append(("deb", package))
            return records[package]
        with patch.object(reuse, "artifact_pair", return_value=artifact_ids()), \
                patch.object(reuse, "download_provenance", side_effect=provenance), \
                patch.object(reuse, "screen_metadata", side_effect=screening), \
                patch.object(reuse, "download_artifact", side_effect=download), \
                patch.object(reuse, "validate_metadata", return_value="immutable") as validate, \
                patch.object(reuse, "run_details", return_value=RUN):
            verified, _ = reuse.verify_pair(RUN, "f" * 64, Path("unused"))
            self.assertEqual(set(verified), set(reuse.PACKAGES))
            self.assertEqual([call.args[2] for call in validate.call_args_list], [RUN, RUN])
            self.assertEqual(events[4:], [("deb", package) for package in reuse.PACKAGES])

    def test_incompatible_lightweight_metadata_never_downloads_any_deb(self):
        for package in reuse.PACKAGES:
            for section, field, value in (
                (None, "fingerprint", "old-inputs"),
                ("identity", "attempt", "2"), ("identity", "head_sha", "b" * 40),
                ("identity", "run_id", "99"), ("deb", "version", "1.10.0-1.build9"),
                ("deb", "architecture", "arm64"), ("deb", "package", "unexpected"),
                ("deb", "size", 0), ("deb", "sha256", "invalid"),
                ("image", "tag", "ghcr.io/owner/debian-cosmic-epoch:latest"),
            ):
                records = {p: metadata(p) for p in reuse.PACKAGES}
                target = records[package] if section is None else records[package][section]
                target[field] = value
                with self.subTest(package=package, field=field), \
                        patch.object(reuse, "artifact_pair", return_value=artifact_ids()), \
                        patch.object(reuse, "download_provenance",
                                     side_effect=lambda _, p, dest: records[p]), \
                        patch.object(reuse, "download_artifact") as download, \
                        patch.object(reuse.shutil, "rmtree"), self.assertRaises(ValueError):
                    reuse.verify_pair(RUN, "f" * 64, Path("unused"))
                download.assert_not_called()

    def test_package_metadata_must_equal_screened_provenance(self):
        records = {p: metadata(p) for p in reuse.PACKAGES}
        changed = metadata() | {"extra": "not in screened record"}
        with patch.object(reuse, "artifact_pair", return_value=artifact_ids()), \
                patch.object(reuse, "download_provenance", side_effect=lambda _, p, dest: records[p]), \
                patch.object(reuse, "download_artifact", return_value=changed) as download, \
                patch.object(reuse, "validate_metadata") as validate, \
                patch.object(reuse, "run_details", return_value=RUN), \
                patch.object(reuse.shutil, "rmtree"), self.assertRaisesRegex(ValueError, "screened"):
            reuse.verify_pair(RUN, "f" * 64, Path("unused"))
        self.assertEqual(download.call_count, 1)
        validate.assert_not_called()

    def test_pair_rejects_changed_run_attempt_or_artifact_identity(self):
        changed_artifacts = artifact_ids()
        changed_artifacts["cosmic-utils"]["provenance"] = "5"
        records = {p: metadata(p) for p in reuse.PACKAGES}
        for phase in ("screening", "download"):
            for changed_run, changed_listing in (
                (RUN | {"run_attempt": 2}, artifact_ids()),
                (RUN, changed_artifacts),
                (RUN | {"conclusion": "failure"}, artifact_ids()),
                (RUN, ValueError("artifact expired")),
            ):
                runs = [changed_run] if phase == "screening" else [RUN, changed_run]
                listings = [artifact_ids(), changed_listing] if phase == "screening" else [
                    artifact_ids(), artifact_ids(), changed_listing,
                ]
                with self.subTest(phase=phase, run=changed_run, listing=changed_listing), \
                        patch.object(reuse, "artifact_pair", side_effect=listings), \
                        patch.object(reuse, "download_provenance", side_effect=lambda _, p, dest: records[p]), \
                        patch.object(reuse, "download_artifact",
                                     side_effect=lambda _, p, dest: records[p]) as download, \
                        patch.object(reuse, "validate_metadata", return_value="immutable"), \
                        patch.object(reuse, "run_details", side_effect=runs), \
                        patch.object(reuse.shutil, "rmtree"), self.assertRaises(ValueError):
                    reuse.verify_pair(RUN, "f" * 64, Path("unused"))
                self.assertEqual(download.call_count, 0 if phase == "screening" else 2)

    def test_fresh_and_non_main_events_never_query_sources(self):
        for event, ref in (("schedule", "refs/heads/main"), ("workflow_dispatch", "refs/heads/main"),
                           ("pull_request", "refs/pull/1/merge"), ("push", "refs/heads/wip/test")):
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref}), \
                    patch.object(reuse, "output") as output, patch.object(reuse, "api") as api:
                reuse.resolve()
                api.assert_not_called()
                output.assert_called_once_with({"run_id": "", "attempt": ""})

    def test_api_failure_rebuilds_without_selection(self):
        with patch.object(reuse, "output") as output, \
                patch.object(reuse, "fingerprint", return_value="f" * 64), \
                patch.object(reuse, "scratch", return_value=Path("unused")), \
                patch.object(reuse.shutil, "rmtree"), \
                patch.object(reuse, "run_details", side_effect=RuntimeError("API unavailable")):
            reuse.resolve()
            output.assert_called_once_with({"run_id": "", "attempt": ""})

    def test_resolver_accepts_only_complete_verified_pair(self):
        candidates = [RUN | {"id": 99}, RUN]
        with patch.object(reuse, "output") as output, \
                patch.object(reuse, "fingerprint", return_value="f" * 64), \
                patch.object(reuse, "scratch", return_value=Path("unused")), \
                patch.object(reuse.shutil, "rmtree"), \
                patch.object(reuse, "api", return_value={"workflow_runs": candidates}), \
                patch.object(reuse, "run_details", side_effect=[RUN | {"id": 200}, candidates[0], RUN]), \
                patch.object(reuse, "verify_pair", side_effect=[ValueError("legacy metadata"), ({}, RUN)]):
            reuse.resolve()
            self.assertEqual(output.call_args_list[-1].args[0], {"run_id": "100", "attempt": "1"})

    def test_unavailable_selected_source_never_promotes_or_falls_back(self):
        with patch.dict(os.environ, {"SOURCE_RUN_ID": "100", "SOURCE_ATTEMPT": "1"}), \
                patch.object(reuse, "run_details", side_effect=[RUN | {"id": 200}, RUN]), \
                patch.object(reuse, "scratch", return_value=MagicMock()), \
                patch.object(reuse.Path, "exists", return_value=False):
            # Use a concrete clean destination; no files are written on failure.
            with patch.object(reuse, "scratch", return_value=Path("unused")), \
                    patch.object(reuse, "fingerprint", return_value="f" * 64), \
                    patch.object(reuse, "verify_pair", side_effect=ValueError("artifact expired")), \
                    patch.object(reuse.shutil, "rmtree"), patch.object(reuse, "command") as command, \
                    self.assertRaises(ValueError):
                reuse.release()
            command.assert_not_called()

    def test_release_promotes_only_selected_digests_after_whole_pair_validation(self):
        verified = {
            package: (MagicMock(), metadata(package), reuse.image_reference(package) + "@" + DIGEST)
            for package in reuse.PACKAGES
        }
        directory = MagicMock()
        directory.__truediv__.return_value.exists.return_value = False
        with patch.dict(os.environ, {"SOURCE_RUN_ID": "100", "SOURCE_ATTEMPT": "1"}), \
                patch.object(reuse, "run_details", side_effect=[RUN | {"id": 200}, RUN]), \
                patch.object(reuse, "scratch", return_value=directory), \
                patch.object(reuse, "fingerprint", return_value="f" * 64), \
                patch.object(reuse, "verify_pair", return_value=(verified, RUN)) as verify, \
                patch.object(reuse.shutil, "copyfile") as copyfile, \
                patch.object(reuse, "registry_digest", return_value=DIGEST), \
                patch.object(reuse, "output") as output, patch.object(reuse, "command") as command:
            reuse.release()
            verify.assert_called_once()
            self.assertEqual(copyfile.call_count, 2)
            self.assertEqual(command.call_count, 2)
            for call, package in zip(command.call_args_list, reuse.PACKAGES):
                self.assertEqual(call.args[0], [
                    "docker", "buildx", "imagetools", "create", "--prefer-index=false",
                    "--tag", reuse.image_reference(package) + ":latest",
                    reuse.image_reference(package) + "@" + DIGEST,
                ])
            self.assertEqual(output.call_args_list[0].args[0]["source_run_id"], "100")

    def test_record_binds_package_hash_to_digest_returned_by_its_push(self):
        current = RUN | {"id": 200, "run_number": 20, "status": "in_progress", "conclusion": None}
        directory = MagicMock(spec=Path)
        path = directory.__truediv__.return_value
        path.name = "cosmic-epoch-monorepo.deb"
        path.stat.return_value.st_size = 12
        path.read_text.return_value = "f" * 64
        directory.glob.return_value = iter([path])
        push_result = subprocess.CompletedProcess([], 0, stdout=f"layer: pushed\nrun-200-attempt-1: digest: {DIGEST} size: 1234\n".encode())
        with patch.dict(os.environ, {"PACKAGE_NAME": "cosmic-epoch", "DIST_DIR": "unused"}), \
                patch.object(reuse, "Path", return_value=directory), \
                patch.object(reuse, "run_details", return_value=current), \
                patch.object(reuse, "deb_headers", return_value={
                    "Package": "cosmic-epoch-monorepo", "Version": "1.10.0-1.build20", "Architecture": "amd64",
                }), patch.object(reuse, "sha256", return_value="d" * 64), \
                patch.object(reuse, "command", return_value=push_result) as command, \
                patch.object(reuse, "registry_digest", return_value=DIGEST) as inspect:
            reuse.record()
            command.assert_called_once_with(
                ["docker", "push", "ghcr.io/owner/debian-cosmic-epoch:run-200-attempt-1"], capture_output=True,
            )
            inspect.assert_called_once_with("ghcr.io/owner/debian-cosmic-epoch@" + DIGEST)
            record = json.loads(path.write_text.call_args.args[0])
            self.assertEqual(record["deb"]["sha256"], "d" * 64)
            self.assertEqual(record["image"]["digest"], DIGEST)
            self.assertEqual(record["identity"]["run_id"], "200")

    def test_identity_and_outputs_reject_injection(self):
        for value in ("1\nrun_id=2", "../1", "0", "-1", "abc"):
            with self.assertRaises(ValueError):
                reuse.numeric(value)
        with patch.object(reuse.Path, "open", return_value=io.StringIO()), \
                patch.dict(os.environ, {"GITHUB_OUTPUT": "unused"}), self.assertRaises(ValueError):
            reuse.output({"run_id": "100\nattempt=9"})

    def test_archive_rejects_path_traversal_and_additional_files(self):
        for filenames in (
            ["../cosmic-epoch-monorepo.deb", "metadata.json"],
            ["cosmic-epoch-monorepo.deb", "metadata.json", "build.sh"],
            ["cosmic-epoch-monorepo.deb"],
        ):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as writer:
                for filename in filenames:
                    writer.writestr(filename, b"content")
            archive.seek(0)
            destination = MagicMock(spec=Path)
            destination.__truediv__.return_value.open.return_value.__enter__.return_value = io.BytesIO()
            with zipfile.ZipFile(archive) as reader, \
                    patch.object(reuse.zipfile, "ZipFile", return_value=reader), \
                    patch.object(reuse, "command"), self.assertRaises(ValueError):
                reuse.download_artifact("1", "cosmic-epoch", destination)

    def test_lightweight_archive_contains_only_bounded_metadata(self):
        record = metadata()
        for files, valid in (
            ({"metadata.json": json.dumps(record)}, True),
            ({"metadata.json": json.dumps(record), "cosmic-epoch-monorepo.deb": "deb"}, False),
            ({"../metadata.json": "{}"}, False),
            ({"metadata.json": "x" * (reuse.MAX_METADATA_SIZE + 1)}, False),
            ({"metadata.json": ""}, False),
        ):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as writer:
                for filename, content in files.items():
                    writer.writestr(filename, content)
            archive.seek(0)
            destination = MagicMock(spec=Path)
            output = destination.__truediv__.return_value
            output.open.return_value.__enter__.return_value = io.BytesIO()
            output.read_text.return_value = json.dumps(record)
            with self.subTest(files=list(files), valid=valid), \
                    zipfile.ZipFile(archive) as reader, \
                    patch.object(reuse.zipfile, "ZipFile", return_value=reader), \
                    patch.object(reuse, "command"):
                if valid:
                    self.assertEqual(reuse.download_provenance("3", "cosmic-epoch", destination), record)
                else:
                    with self.assertRaises(ValueError):
                        reuse.download_provenance("3", "cosmic-epoch", destination)


if __name__ == "__main__":
    unittest.main()
