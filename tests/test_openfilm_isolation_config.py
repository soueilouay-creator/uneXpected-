import os
import unittest
from unittest.mock import patch

from unexpected_runtime.media.isolation import IsolationError, PodmanIsolationConfig, WorkerResourceLimits


class PodmanIsolationConfigTests(unittest.TestCase):
    def test_from_env_requires_a_pinned_local_image_and_explicit_host_ceilings(self):
        values = {
            "UNEXPECTED_OPENFILM_PODMAN_PATH": "/usr/bin/podman",
            "UNEXPECTED_OPENFILM_WORKER_IMAGE": "sha256:" + "a" * 64,
            "UNEXPECTED_OPENFILM_HOST_MAX_MEMORY_BYTES": "3221225472",
            "UNEXPECTED_OPENFILM_HOST_MAX_CPU_LIMIT": "1.5",
            "UNEXPECTED_OPENFILM_HOST_MAX_PIDS": "128",
            "UNEXPECTED_OPENFILM_HOST_TMPFS_BYTES": "1073741824",
        }
        with patch.dict(os.environ, values, clear=True):
            config = PodmanIsolationConfig.from_env()
        self.assertEqual(config.image, "sha256:" + "a" * 64)
        self.assertEqual(config.max_pids, 128)

    def test_from_env_rejects_missing_settings_and_mutable_image_tags(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(IsolationError):
                PodmanIsolationConfig.from_env()
        with self.assertRaises(ValueError):
            PodmanIsolationConfig(
                podman_path=__import__("pathlib").Path("/usr/bin/podman"),
                image="localhost/worker:latest",
            )

    def test_host_limits_are_validated_before_a_job_can_be_claimed(self):
        config = PodmanIsolationConfig(
            podman_path=__import__("pathlib").Path("/usr/bin/podman"),
            image="sha256:" + "b" * 64,
            max_memory_bytes=1024,
            max_cpu_limit=1.0,
            max_pids=8,
            tmpfs_bytes=1024,
        )
        limits = WorkerResourceLimits(
            memory_bytes=2048, cpu_limit=1.0, pids_limit=8,
            tmpfs_bytes=1024, max_output_bytes=1024,
        )
        with self.assertRaises(ValueError):
            limits.validate(config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
