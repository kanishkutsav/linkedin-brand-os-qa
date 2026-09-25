from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from urllib.parse import quote
import httpx

from app.core.config import settings


class LinkedInAnalyticsService:
    """Read-only member creator analytics through LinkedIn's official API."""

    DAILY_METRICS = ("IMPRESSION", "REACTION", "COMMENT", "RESHARE")
    TOTAL_METRICS = ("MEMBERS_REACHED",)

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base = (settings.linkedin_api_base_url or "https://api.linkedin.com").rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": settings.linkedin_api_version,
        }

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base}{path}",
                params=params,
                headers=self._headers(),
            )
        if response.status_code >= 400:
            detail = response.text[:600]
            raise RuntimeError(f"LinkedIn analytics API returned HTTP {response.status_code}: {detail}")
        return response.json()

    @staticmethod
    def _metric_name(element: dict) -> str:
        metric = element.get("metricType")
        if isinstance(metric, str):
            return metric
        if isinstance(metric, dict):
            return str(next(iter(metric.values()), "") or "")
        return ""

    @staticmethod
    def _date_key(element: dict) -> str | None:
        date_range = element.get("dateRange") or {}
        start = date_range.get("start") or {}
        if not start:
            return None
        try:
            return date(int(start["year"]), int(start["month"]), int(start["day"])).isoformat()
        except (KeyError, TypeError, ValueError):
            return None

    async def fetch(self, days: int = 30) -> dict:
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=max(7, min(days, 90)))
        date_range = f"(start:(year:{start.year},month:{start.month},day:{start.day}),end:(year:{end.year},month:{end.month},day:{end.day}))"

        async def metric(metric: str, aggregation: str) -> tuple[str, dict]:
            data = await self._get(
                "/rest/memberCreatorPostAnalytics",
                {
                    "q": "me",
                    "queryType": metric,
                    "aggregation": aggregation,
                    "dateRange": date_range,
                },
            )
            return metric, data

        # LinkedIn does not support MEMBERS_REACHED + DAILY. Fetch that metric
        # as a total and the remaining metrics as daily series in parallel.
        results = await asyncio.gather(
            *(metric(item, "DAILY") for item in self.DAILY_METRICS),
            *(metric(item, "TOTAL") for item in self.TOTAL_METRICS),
        )
        daily: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = {item: 0 for item in (*self.DAILY_METRICS, *self.TOTAL_METRICS)}

        for metric_name, payload in results:
            for element in payload.get("elements") or []:
                count = int(element.get("count") or 0)
                totals[metric_name] += count
                day = self._date_key(element)
                if day:
                    daily.setdefault(day, {})[metric_name] = count

        trend = []
        for day in sorted(daily):
            row = {"date": day}
            row.update({metric: daily[day].get(metric, 0) for metric in self.METRICS})
            row["engagement"] = row["REACTION"] + row["COMMENT"] + row["RESHARE"]
            row["MEMBERS_REACHED"] = 0
            row["engagement_rate"] = round(
                (row["engagement"] / row["IMPRESSION"]) * 100, 2
            ) if row["IMPRESSION"] else 0
            trend.append(row)

        return {
            "available": True,
            "window_days": max(7, min(days, 90)),
            "from": start.isoformat(),
            "to": (end - timedelta(days=1)).isoformat(),
            "totals": totals,
            "engagement_total": totals["REACTION"] + totals["COMMENT"] + totals["RESHARE"],
            "engagement_rate": round(
                ((totals["REACTION"] + totals["COMMENT"] + totals["RESHARE"]) / totals["IMPRESSION"]) * 100,
                2,
            ) if totals["IMPRESSION"] else 0,
            "trend": trend,
            "source": "LinkedIn memberCreatorPostAnalytics",
        }
