import unittest

from fastapi.testclient import TestClient

from app.main import app


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_strategy_recommend_endpoint(self):
        payload = {"goal": "build authority in AI adoption", "audience": "product leaders"}
        response = self.client.post("/api/strategy/recommend", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("content_mix", response.json())

    def test_research_evidence_endpoint(self):
        payload = {
            "topic": "AI adoption in enterprise settings",
            "audience": "engineering leaders",
            "sources": [
                {"title": "AI adoption guide", "url": "https://example.com/ai-guide", "summary": "Companies proceed in waves."},
            ],
        }
        response = self.client.post("/api/research/evidence", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("facts", response.json())

    def test_voice_profile_endpoint(self):
        payload = {
            "approved_examples": [
                "I’ve learned this the hard way: simple systems beat clever complexity.",
                "Most teams over-invest in tools and under-invest in alignment.",
            ]
        }
        response = self.client.post("/api/voice/profile", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("tone", response.json())

    def test_profile_and_dashboard_flow(self):
        profile_response = self.client.post(
            "/api/profile",
            json={
                "display_name": "Ava",
                "professional_title": "AI strategy lead",
                "industry": "B2B SaaS",
                "audience": "product leaders",
                "goals": ["build authority", "increase signal"],
                "brand_positioning": "clear, practical, anti-hype",
                "tone": "direct and grounded",
            },
        )
        self.assertEqual(profile_response.status_code, 200)
        dashboard_response = self.client.get("/api/dashboard/approvals")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("pending_approvals", dashboard_response.json())

    def test_approval_edit_and_reject_flow(self):
        draft = self.client.post(
            "/api/content/drafts",
            json={
                "title": "Simple systems beat complexity",
                "topic": "AI adoption in product teams",
                "pillar": "Expertise",
                "body": "Most teams over-invest in tools and under-invest in alignment.",
            },
        )
        approval_id = draft.json()["approval_id"]
        self.assertIsNotNone(approval_id)

        edited = self.client.post(
            f"/api/approvals/{approval_id}/edit",
            json={"edited_body": "Most teams over-invest in tools and under-invest in alignment. That is the real bottleneck.", "reason": "Tightened clarity."},
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["status"], "EDITED")

        rejected = self.client.post(
            f"/api/approvals/{approval_id}/reject",
            json={"reason": "Too opinionated for this audience."},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
