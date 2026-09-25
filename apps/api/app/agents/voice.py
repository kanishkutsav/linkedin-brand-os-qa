from __future__ import annotations


class VoiceProfileBuilder:
    """Builds a practical voice profile from approved examples and user feedback."""

    def learn(self, approved_examples: list[str]) -> dict:
        preferred_phrases = []
        for example in approved_examples:
            words = [token.strip(" ,.;:!?\"") for token in example.lower().split()]
            for word in words:
                if word and len(word) > 4 and word not in {"these", "those", "about", "there"}:
                    preferred_phrases.append(word)

        return {
            "tone": "practical, direct, credible",
            "sentence_style": "clear, concise, grounded in lived experience",
            "vocabulary": [
                "alignment",
                "systems",
                "execution",
                "tradeoffs",
                "clarity",
                "practicality",
            ],
            "preferred_phrases": preferred_phrases[:12],
            "avoid_phrases": [
                "game-changer",
                "delve into",
                "unlock the power of",
                "in today's rapidly evolving",
                "synergy",
            ],
            "emoji_usage": "limited, only in low-risk, human moments",
            "humor_style": "dry and observational",
            "technical_depth": "moderate to high",
            "opinion_style": "clear and grounded, not performative",
            "storytelling_style": "evidence-driven and concrete",
        }
