import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from unexpected_runtime.capabilities import CapabilityRecord, CapabilityRegistry
from unexpected_runtime.media.jobs import MediaJobService
from unexpected_runtime.media.openfilm_adapter import (
    OpenFilmAdapter, OpenFilmAdapterError, ROLE_IDS, TOOL_CANCEL, TOOL_CREATE, TOOL_STATUS,
)
from unexpected_runtime.mcp_gateway import MCPToolGateway
from unexpected_runtime.permissions import PermissionPolicy
from unexpected_runtime.registry import AgentRegistry
from unexpected_runtime.storage import StateStore


class OpenFilmAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.temp.name) / "state.sqlite3")
        self.jobs = MediaJobService(self.store)
        self.agents = AgentRegistry.load()
        self.permissions = PermissionPolicy()
        self.digest = hashlib.sha256(b"pinned OpenFilm adapter fixture").hexdigest()
        self.record = CapabilityRecord(
            capability_id="media.openfilm.render",
            name="OpenFilm local renderer",
            category="media",
            purpose="Create and inspect local OpenFilm render jobs",
            source_url="https://github.com/openfilm/openfilm",
            source_publisher="OpenFilm contributors",
            discovered_at=time.time(),
            verified_at=None,
            evidence_refs=("https://github.com/openfilm/openfilm/tree/v0.2.7",),
            reviewer=None,
            adapter_type="mcp",
            provider="openfilm",
            required_permissions=("media.local_render",),
            dependencies=("node>=22.18", "openfilm@0.2.7", "ffmpeg", "playwright-chromium"),
            cost_notes="Local rendering only; no paid media-generation provider.",
            risk_notes="Project HTML/JavaScript is untrusted and requires sandbox isolation.",
            data_access=("configured-project-root", "configured-artifact-root"),
            version="0.2.7",
            content_sha256=self.digest,
            status="discovered",
        )
        self.capabilities = CapabilityRegistry(self.store)
        self.capabilities.register(self.record)
        self.capabilities.transition(
            self.record.capability_id, "reviewed", reviewer="test-owner", reason="test provenance"
        )
        self.capabilities.transition(
            self.record.capability_id, "installed", reason="fixture adapter package"
        )
        self.adapter = OpenFilmAdapter(self.jobs, self.record)
        self.gateway = MCPToolGateway(
            store=self.store,
            capabilities=self.capabilities,
            permissions=self.permissions,
            agent_registry=self.agents,
        )
        self.gateway.register_adapter(self.record.capability_id, self.adapter)

    def tearDown(self):
        self.gateway.close()
        self.temp.cleanup()

    def call_tool(self, tool_id, arguments, role="media-producer"):
        return self.gateway.call(
            agent_id=role,
            task_id="task-openfilm-1",
            tool_id=tool_id,
            arguments=arguments,
        )

    def create_args(self):
        return {
            "task_id": "task-openfilm-1",
            "idempotency_key": "render-request-1",
            "project_path": "maintenance-explainer/film.html",
            "campaign_id": "MAINTENANCE_TRACKER_GROWTH",
            "content_id": "YT-TRACKER-TEST-01",
            "synthetic_data": True,
            "rights_manifest": {"sources": [{"kind": "original", "owner": "uneXpected"}]},
            "variants": [
                {"platform": "youtube_shorts", "width": 1080, "height": 1920},
                {"platform": "tiktok", "width": 1080, "height": 1920},
            ],
        }

    def test_exact_three_tools_are_exposed_and_queue_without_rendering(self):
        descriptors = self.adapter.describe()
        self.assertEqual({item.tool_id for item in descriptors}, {TOOL_CREATE, TOOL_STATUS, TOOL_CANCEL})
        self.assertTrue(all(item.timeout_seconds <= 30 for item in descriptors))
        self.capabilities.transition(
            self.record.capability_id, "enabled", reason="test fixture adapter verification"
        )
        queued = self.call_tool(TOOL_CREATE, self.create_args())
        self.assertEqual(queued["state"], "queued")
        self.assertFalse(queued["replayed"])
        self.assertEqual(len(self.jobs.list(state="queued")), 1)

    def test_create_is_idempotent_and_status_is_bounded(self):
        self.capabilities.transition(
            self.record.capability_id, "enabled", reason="test fixture adapter verification"
        )
        first = self.call_tool(TOOL_CREATE, self.create_args())
        replay = self.call_tool(TOOL_CREATE, self.create_args())
        self.assertEqual(first["job_id"], replay["job_id"])
        self.assertTrue(replay["replayed"])
        status = self.call_tool(TOOL_STATUS, {"job_id": first["job_id"]})
        self.assertEqual(status["state"], "queued")
        self.assertNotIn("request_json", status)
        self.assertNotIn("lease_token", status)

    def test_cancel_reports_persisted_state_without_claiming_worker_stopped(self):
        self.capabilities.transition(
            self.record.capability_id, "enabled", reason="test fixture adapter verification"
        )
        queued = self.call_tool(TOOL_CREATE, self.create_args())
        result = self.call_tool(TOOL_CANCEL, {"job_id": queued["job_id"]})
        self.assertEqual(result["state"], "cancelled")

    def test_only_four_named_roles_are_allowed(self):
        self.assertEqual(
            set(ROLE_IDS),
            {"orchestrator", "creative-director", "media-producer", "voice-agent"},
        )
        self.capabilities.transition(
            self.record.capability_id, "enabled", reason="test fixture adapter verification"
        )
        with self.assertRaises(Exception):
            self.call_tool(TOOL_CREATE, self.create_args(), role="research-scout")

    def test_unsafe_paths_and_wrong_variant_dimensions_are_rejected(self):
        for path in ("/etc/passwd", "../secret/film.html", ".runtime/film.html", "x\\y/film.html"):
            args = self.create_args()
            args["project_path"] = path
            with self.subTest(path=path), self.assertRaises(OpenFilmAdapterError):
                self.adapter.call(TOOL_CREATE, args, None)
        args = self.create_args()
        args["variants"][0]["width"] = 720
        with self.assertRaises(OpenFilmAdapterError):
            self.adapter.call(TOOL_CREATE, args, None)

    def test_unknown_fields_and_unknown_job_ids_fail_closed(self):
        args = self.create_args()
        args["shell_command"] = "echo unsafe"
        with self.assertRaises(OpenFilmAdapterError):
            self.adapter.call(TOOL_CREATE, args, None)
        with self.assertRaises(OpenFilmAdapterError):
            self.adapter.call(TOOL_STATUS, {"job_id": "missing"}, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
