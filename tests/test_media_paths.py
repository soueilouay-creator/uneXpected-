import os
import tempfile
import unittest
from pathlib import Path

from unexpected_runtime.media.paths import MediaPathError, MediaPathPolicy


class MediaPathPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.artifacts = self.root / "artifacts"
        self.project = self.projects / "pilot"
        self.project.mkdir(parents=True)
        self.artifacts.mkdir()
        (self.project / "film.html").write_text("<html></html>", encoding="utf-8")
        (self.project / "scene.css").write_text("body{margin:0}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_project_returns_bounded_inventory_and_digest(self):
        policy = MediaPathPolicy(max_project_bytes=1024, max_asset_count=10, max_file_bytes=1024)
        result = policy.inspect_project(self.projects, "pilot")
        self.assertEqual(result.project_root, self.project.resolve())
        self.assertEqual(result.entrypoint, self.project / "film.html")
        self.assertEqual(result.asset_count, 2)
        self.assertGreater(result.total_bytes, 0)
        self.assertEqual(len(result.sha256), 64)

    def test_rejects_absolute_and_traversal_project_paths(self):
        policy = MediaPathPolicy()
        for value in ("../outside", "/etc", ".", "pilot/../outside", "pilot\\secret"):
            with self.subTest(path=value), self.assertRaises(MediaPathError):
                policy.inspect_project(self.projects, value)

    def test_rejects_symlink_files_and_directories(self):
        external = self.root / "external.txt"
        external.write_text("outside", encoding="utf-8")
        (self.project / "leak.txt").symlink_to(external)
        policy = MediaPathPolicy()
        with self.assertRaises(MediaPathError):
            policy.inspect_project(self.projects, "pilot")

    def test_rejects_hidden_runtime_directories_and_unsupported_assets(self):
        hidden = self.project / ".git"
        hidden.mkdir()
        with self.assertRaises(MediaPathError):
            MediaPathPolicy().inspect_project(self.projects, "pilot")
        hidden.rmdir()
        (self.project / "payload.bin").write_bytes(b"x")
        with self.assertRaises(MediaPathError):
            MediaPathPolicy().inspect_project(self.projects, "pilot")

    def test_rejects_project_byte_and_asset_count_limits(self):
        (self.project / "large.txt").write_bytes(b"x" * 200)
        with self.assertRaises(MediaPathError):
            MediaPathPolicy(max_project_bytes=100, max_asset_count=20, max_file_bytes=100).inspect_project(self.projects, "pilot")
        (self.project / "large.txt").unlink()
        with self.assertRaises(MediaPathError):
            MediaPathPolicy(max_project_bytes=1024, max_asset_count=1, max_file_bytes=1024).inspect_project(self.projects, "pilot")

    def test_attempt_directory_is_unique_and_never_overwritten(self):
        policy = MediaPathPolicy(artifact_root=self.artifacts)
        attempt = policy.prepare_attempt("job-1", 1)
        self.assertTrue(attempt.is_dir())
        self.assertEqual(attempt.parent.name, "job-1")
        with self.assertRaises(MediaPathError):
            policy.prepare_attempt("job-1", 1)

    def test_rejects_symlinked_artifact_root(self):
        target = self.root / "real-artifacts"
        target.mkdir()
        link = self.root / "artifact-link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(MediaPathError):
            MediaPathPolicy(artifact_root=link).prepare_attempt("job-2", 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
