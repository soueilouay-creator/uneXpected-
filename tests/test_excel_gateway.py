from __future__ import annotations
import http.client
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace

from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.http_api import create_server
from unexpected_runtime.providers import ProviderResponse


UPLOAD_ID = "123e4567-e89b-42d3-a456-426614174000"
ARTIFACT_ID = "223e4567-e89b-42d3-a456-426614174000"
XLSX_BYTES = bytes((0x50, 0x4b, 0x03, 0x04)) + b"fake-xlsx-package"
ARTIFACT_BYTES = bytes((0x50, 0x4b, 0x03, 0x04)) + b"generated-xlsx"


class FakeExcelGateway:
    name = "unexpected-ai-studio-gateway"
    configured = True
    supports_excel_files = True

    def __init__(self):
        self.uploads = []
        self.attached_ids = []
        self.downloads = []

    def upload_workbook(self, data, file_name, timeout=30):
        self.uploads.append((data, file_name, timeout))
        return {
            "id": UPLOAD_ID,
            "name": file_name,
            "sizeBytes": len(data),
            "expiresInSeconds": 1800,
        }

    def generate(self, *, system_prompt, user_prompt, agent_id, task_id, timeout, excel_file_ids=()):
        self.attached_ids = list(excel_file_ids)
        return ProviderResponse(
            text="Live Excel gateway response: workbook generated and verified.",
            excel_artifacts=({
                "id": ARTIFACT_ID,
                "fileName": "report.xlsx",
                "sizeBytes": len(ARTIFACT_BYTES),
                "expiresInSeconds": 1800,
                "downloadPath": "/excel/download/" + ARTIFACT_ID,
            },),
        )

    def download_artifact(self, artifact_id, timeout=30):
        self.downloads.append((artifact_id, timeout))
        if artifact_id != ARTIFACT_ID:
            raise ValueError("Unknown artifact")
        return {"bytes": ARTIFACT_BYTES, "fileName": "report.xlsx", "sizeBytes": len(ARTIFACT_BYTES)}


class ExcelGatewayAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.provider = FakeExcelGateway()
        self.coordinator = Coordinator(
            state_dir=self.tmp.name, provider=self.provider, max_workers=1, max_retries=0
        )
        self.server = create_server(
            coordinator=self.coordinator, api_token="a" * 48, host="127.0.0.1", port=0
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.coordinator.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, *, token="a" * 48, headers=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=8)
        outgoing = dict(headers or {})
        if token:
            outgoing["Authorization"] = "Bearer " + token
        conn.request(method, path, body, outgoing)
        response = conn.getresponse()
        data = response.read()
        result_headers = dict(response.getheaders())
        conn.close()
        return response.status, result_headers, data

    def upload(self, *, token="a" * 48):
        return self.request(
            "POST",
            "/v1/excel/upload",
            XLSX_BYTES,
            token=token,
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "X-File-Name": "source.xlsx",
            },
        )

    def invoke(self, file_ids):
        body = json.dumps({
            "agent_id": "data-analyst",
            "objective": "Inspect this Excel workbook and report data-quality issues.",
            "inputs": {"excel_file_ids": file_ids},
        }).encode()
        return self.request(
            "POST", "/v1/invoke", body,
            headers={"Content-Type": "application/json"},
        )

    def test_excel_upload_requires_runtime_authentication(self):
        status, _, _ = self.upload(token="")
        self.assertEqual(status, 401)

    def test_excel_upload_is_bounded_and_returns_a_request_attachment_id(self):
        status, _, raw = self.upload()
        self.assertEqual(status, 201, raw)
        payload = json.loads(raw)
        self.assertTrue(payload["file"]["id"])
        self.assertEqual(payload["file"]["name"], "source.xlsx")
        self.assertEqual(payload["file"]["sizeBytes"], len(XLSX_BYTES))
        self.assertEqual(self.provider.uploads[0][0], XLSX_BYTES)

    def test_only_uploaded_file_ids_can_be_attached_to_an_invoke(self):
        status, _, _ = self.invoke([UPLOAD_ID])
        self.assertEqual(status, 403)
        self.assertEqual(self.provider.attached_ids, [])

    def test_uploaded_workbook_is_attached_and_verified_artifact_can_be_downloaded(self):
        upload_status, _, upload_raw = self.upload()
        self.assertEqual(upload_status, 201, upload_raw)
        uploaded_id = json.loads(upload_raw)["file"]["id"]

        status, _, raw = self.invoke([uploaded_id])
        self.assertEqual(status, 200, raw)
        payload = json.loads(raw)["result"]
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["output_artifacts"][0]["download_path"], "/v1/excel/artifacts/" + ARTIFACT_ID)
        self.assertEqual(self.provider.attached_ids, [uploaded_id])

        denied, _, _ = self.request("GET", "/v1/excel/artifacts/" + ARTIFACT_ID, token="")
        self.assertEqual(denied, 401)
        downloaded, headers, data = self.request("GET", "/v1/excel/artifacts/" + ARTIFACT_ID)
        self.assertEqual(downloaded, 200)
        self.assertEqual(data, ARTIFACT_BYTES)
        self.assertIn("spreadsheetml", headers.get("Content-Type", ""))
        self.assertIn("report.xlsx", headers.get("Content-Disposition", ""))
        self.assertEqual(self.provider.downloads[0][0], ARTIFACT_ID)


if __name__ == "__main__":
    unittest.main(verbosity=2)
