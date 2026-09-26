import unittest

from fastapi.testclient import TestClient

from app.main import app


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_strategy_recommend_endpoint(self):
        payload = {"focus": "AI adoption"}
        response = self.client.post("/api/strategy/recommend", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("content_mix", response.json())

    def test_research_evidence_endpoint(self):
        payload = {
            "topic": "AI adoption in enterprise settings",
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

    def test_current_onboarding_disables_manual_profile_writes(self):
        response = self.client.post(
            "/api/profile",
            json={
                "display_name": "Ava",
                "professional_title": "AI strategy lead",
                "industry": "B2B SaaS",
                "tone": "direct and grounded",
                "experience_years": 8,
            },
        )
        self.assertEqual(response.status_code, 410)

    def test_dashboard_and_approval_routes_are_registered(self):
        routes = {route.path for route in self.client.app.routes}
        self.assertIn("/api/dashboard/approvals", routes)
        self.assertIn("/api/approvals/pending", routes)


if __name__ == "__main__":
    unittest.main()
