from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from google import genai
from google.genai import types

from app.core.config import settings


class ModelRouterService:
    """OpenRouter-first LLM router with Groq and Gemini fallbacks.

    User-entered Brand DNA is passed in the generation prompt, so every
    configured provider receives the same title, industry, experience, tone,
    Brand Intelligence memory and historical writing evidence.
    No provider is allowed to perform external LinkedIn actions.
    """

    def __init__(self) -> None:
        if not settings.openrouter_api_key and not settings.groq_api_key and not settings.gemini_api_key:
            raise RuntimeError(
                "No LLM provider is configured. Set OPENROUTER_API_KEY, GROQ_API_KEY or GEMINI_API_KEY."
            )

    async def generate_json(
        self,
        system_instruction: str,
        prompt: str,
        *,
        max_output_tokens: int = 1800,
    ) -> dict:
        errors: list[str] = []

        if settings.openrouter_api_key:
            try:
                return await self._openrouter_json(
                    system_instruction,
                    prompt,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                errors.append(f"openrouter: {exc}")

        if settings.groq_api_key:
            try:
                return await self._groq_json(
                    system_instruction,
                    prompt,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                errors.append(f"groq: {exc}")

        if settings.gemini_api_key:
            try:
                return await self._gemini_json(
                    system_instruction,
                    prompt,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                errors.append(f"gemini: {exc}")

        raise RuntimeError(
            "All configured LLM providers failed. " + " | ".join(errors)
        )

    async def _openrouter_json(
        self,
        system_instruction: str,
        prompt: str,
        *,
        max_output_tokens: int,
    ) -> dict:
        payload = {
            "model": settings.openrouter_model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.frontend_url or "",
            "X-Title": settings.app_name,
        }

        # Free-tier routing should fail over quickly instead of holding the UI
        # for the old 90-second provider timeout.
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                settings.openrouter_base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        content = self._extract_content(data)
        return self._parse_json(content, "OpenRouter")

    async def _groq_json(
        self,
        system_instruction: str,
        prompt: str,
        *,
        max_output_tokens: int,
    ) -> dict:
        payload = {
            "model": settings.groq_model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                settings.groq_base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        content = self._extract_content(data)
        return self._parse_json(content, "Groq")

    async def _gemini_json(
        self,
        system_instruction: str,
        prompt: str,
        *,
        max_output_tokens: int,
    ) -> dict:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                max_output_tokens=max_output_tokens,
            ),
        )
        content = getattr(response, "text", None)
        if not content:
            raise RuntimeError("Gemini returned an empty response.")
        return self._parse_json(str(content), "Gemini")

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Provider returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("Provider returned an empty response.")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        return str(content)

    @staticmethod
    def _parse_json(content: str, provider: str) -> dict:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{provider} returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{provider} returned JSON that is not an object.")
        return parsed

    async def create_post(
        self,
        *,
        profile: dict,
        topic: str,
        pillar: str,
        objective: str,
        evidence: list[dict],
        voice: dict,
        feedback: str | None = None,
        current_draft: str | None = None,
    ) -> dict:
        system = """You are the writing engine for a professional LinkedIn personal-brand assistant.
Create useful, credible content for a real person.

Hard rules:
- Never invent the user's experiences, achievements, credentials, metrics, clients, employers, opinions, or first-hand observations.
- Do not present model knowledge as newly researched fact.
- Treat brand_intelligence as durable instructions about the user's identity, expertise, themes and writing patterns.
- Treat learning_memory as observed behavior, not absolute truth. Weight high-confidence repeated signals more than one-off events.
- A research query signals interest, not belief. A personal thought signals a possible viewpoint, not a published position. Approved and published content is the strongest evidence.
- Never reveal or mention the internal learning system in the post.
- Use historical_examples to learn structure, specificity, pacing and voice; do not copy their sentences or pretend a historical example is a new experience.
- Prefer the user's observed themes and real experience signals over generic technology commentary.
- Do not force every post to mention AI, automation or technology unless the supplied brand context supports it.
- Write like a thoughtful professional actually speaking to peers, not like a content marketer or AI assistant.
- Vary sentence length and paragraph rhythm. Natural fragments are allowed when they sound intentional.
- Prefer concrete observations, small tensions, trade-offs, lessons and practical questions over polished slogans.
- Avoid formulaic hooks such as "In today's fast-changing world", "The future of", "X is no longer...", "Here's the thing", "Let that sink in", "Game changer", and similar templates.
- Never use em dashes, en dashes or semicolons. Use commas, periods or line breaks instead. Avoid colon-heavy lists, repetitive three-part constructions, buzzwords, motivational filler, broad 'future of work' commentary and obvious AI-generated phrasing.
- Do not over-explain. Leave some room for the reader to think.
- If a claim is not supported by supplied evidence or profile context, phrase it as a general observation or omit it.
- Do not use generic AI-marketing language.
- Do not use fake quotations.
- Do not use hashtags unless they materially help.
- Use ordinary human wording. Prefer simple verbs and concrete language over polished corporate vocabulary. The final body must contain no em dash, en dash or semicolon. Keep the post human, specific, practical, and concise.
- Return JSON only."""
        prompt = json.dumps(
            {
                "profile": profile,
                "topic": topic,
                "pillar": pillar,
                "objective": objective,
                "evidence": evidence,
                "voice": voice,
                "feedback": feedback or "",
                "current_draft": current_draft or "",
                "generation_rules": {

                    "use_brand_memory": True,
                    "use_learning_memory": True,
                    "learning_is_observational_not_authoritative": True,
                    "use_historical_examples_as_style_reference_only": True,
                    "never_copy_historical_sentences": True,
                    "never_invent_personal_experience": True,
                },
                "output_schema": {
                    "title": "short internal title",
                    "angle": "one sentence describing the point of view",
                    "body": "LinkedIn post text, normally 120-280 words",
                    "claims": [
                        {
                            "text": "claim made in the post",
                            "support": "evidence index or profile context or general observation",
                        }
                    ],
                    "confidence": "high|medium|low",
                },
            },
            ensure_ascii=False,
        )
        return await self.generate_json(system, prompt, max_output_tokens=900)


class GeminiService:
    """Legacy Gemini wrapper retained for web-grounded research.

    Gemini Search grounding remains separate because OpenRouter's web-search
    plugin is a paid add-on rather than part of its free inference allowance.
    """

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model

    async def research_json(self, system_instruction: str, prompt: str) -> tuple[dict, dict]:
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                max_output_tokens=2600,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini research returned an empty response.")

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini research returned invalid JSON.") from exc

        metadata: dict = {"queries": [], "sources": []}
        try:
            candidate = response.candidates[0]
            grounding = getattr(candidate, "grounding_metadata", None)
            if grounding:
                metadata["queries"] = list(
                    getattr(grounding, "web_search_queries", None) or []
                )
                for chunk in list(
                    getattr(grounding, "grounding_chunks", None) or []
                ):
                    web = getattr(chunk, "web", None)
                    if web:
                        metadata["sources"].append(
                            {
                                "title": getattr(web, "title", None),
                                "url": getattr(web, "uri", None),
                            }
                        )
        except Exception:
            pass

        return parsed, metadata
