import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.integrations.linkedin import MockLinkedInAdapter, OfficialLinkedInAdapter
from app.main import app


class _FakeResponse:
    def __init__(self, payload=None, status=201, headers=None):
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def read(self):
        return json.dumps(self._payload).encode("utf-8") if self._payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestPhase7LinkedIn(unittest.TestCase):
    def test_mock_publish_is_explicitly_non_external(self):
        result = MockLinkedInAdapter().publish_post("hello")
        self.assertTrue(result.success)
        self.assertEqual(result.external_id, "mock-post-001")
        self.assertIn("no external LinkedIn action", result.message)

    def test_official_adapter_uploads_image_before_creating_post(self):
        calls = []

        def fake_urlopen(request, timeout=20):
            calls.append({
                "url": request.full_url,
                "method": request.method,
                "headers": dict(request.headers),
                "body": request.data,
            })
            if request.full_url.endswith("/rest/images?action=initializeUpload"):
                return _FakeResponse({
                    "value": {
                        "uploadUrl": "https://upload.example.test/image",
                        "image": "urn:li:image:test-image",
                    }
                }, status=201)
            if request.full_url == "https://upload.example.test/image":
                return _FakeResponse(None, status=201)
            if request.full_url.endswith("/rest/posts"):
                return _FakeResponse(None, status=201, headers={"x-restli-id": "urn:li:share:test-post"})
            raise AssertionError(f"Unexpected LinkedIn URL: {request.full_url}")

        with patch("app.integrations.linkedin.urllib.request.urlopen", side_effect=fake_urlopen):
            result = OfficialLinkedInAdapter("token", "member-123").publish_post(
                "A human-approved post",
                b"\x89PNG\r\n\x1a\nimage",
                "image/png",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.external_id, "urn:li:share:test-post")
        self.assertEqual(result.image_urn, "urn:li:image:test-image")
        self.assertEqual([call["method"] for call in calls], ["POST", "PUT", "POST"])

        post_payload = json.loads(calls[2]["body"].decode("utf-8"))
        self.assertEqual(post_payload["author"], "urn:li:person:member-123")
        self.assertEqual(post_payload["content"]["media"]["id"], "urn:li:image:test-image")

    def test_official_adapter_rejects_unsupported_image_mime(self):
        result = OfficialLinkedInAdapter("token", "member-123").publish_post(
            "post",
            b"data",
            "application/pdf",
        )
        self.assertFalse(result.success)
        self.assertIn("Only JPEG, PNG, or GIF", result.message)

    def test_phase8_readiness_route_is_registered(self):
        routes = {route.path for route in app.routes}
        self.assertIn("/health", routes)
        self.assertIn("/health/ready", routes)
        self.assertIn("/api/approvals/{approval_id}/publication", routes)
        self.assertIn("/api/internal/scheduled-jobs/{job_name}", routes)

    def test_vercel_runtime_does_not_start_in_process_scheduler(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False), \
             patch("app.main.agent_scheduler.start") as start, \
             patch("app.main.agent_scheduler.stop", new_callable=AsyncMock) as stop:
            from fastapi.testclient import TestClient
            with TestClient(app) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
        start.assert_not_called()
        stop.assert_not_awaited()

    def test_linkedin_api_version_is_configurable(self):
        self.assertTrue(settings.linkedin_api_version)


if __name__ == "__main__":
    unittest.main()
