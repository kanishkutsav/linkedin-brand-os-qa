import unittest

from app.agents.research import ResearchService
from app.agents.strategy import ContentStrategyService
from app.agents.voice import VoiceProfileBuilder


class TestMVPAgents(unittest.TestCase):
    def test_strategy_service_recommends_content_mix(self):
        strategy = ContentStrategyService()
        recommendations = strategy.recommend(goal="build authority in AI adoption", audience="senior product leaders")

        self.assertIn("content_mix", recommendations)
        self.assertIn("content_calendar", recommendations)
        self.assertGreater(len(recommendations["content_mix"]), 0)
        self.assertGreater(len(recommendations["content_calendar"]), 0)

    def test_voice_profile_builder_creates_style_profile(self):
        builder = VoiceProfileBuilder()
        profile = builder.learn(
            approved_examples=[
                "I’ve learned this the hard way: simple systems beat clever complexity.",
                "Most teams over-invest in tools and under-invest in alignment.",
            ]
        )

        self.assertIn("tone", profile)
        self.assertIn("preferred_phrases", profile)
        self.assertIn("avoid_phrases", profile)
        self.assertTrue(profile["preferred_phrases"])

    def test_research_service_creates_evidence_pack(self):
        service = ResearchService()
        pack = service.build_evidence_pack(
            topic="AI adoption in enterprise settings",
            audience="engineering leaders",
            sources=[
                {"title": "AI adoption guide", "url": "https://example.com/ai-guide", "summary": "Companies proceed in waves."},
                {"title": "Leadership patterns", "url": "https://example.com/leadership", "summary": "Alignment matters more than hype."},
            ],
        )

        self.assertIn("facts", pack)
        self.assertIn("sources", pack)
        self.assertGreater(len(pack["sources"]), 0)


if __name__ == "__main__":
    unittest.main()
