import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class PublishResult:
    success: bool
    external_id: str | None
    message: str
    image_urn: str | None = None


class LinkedInAdapter:
    """Official LinkedIn API boundary. No browser automation or private APIs."""

    def publish_post(self, body: str, image_bytes: bytes | None = None, image_mime: str | None = None) -> PublishResult:
        raise NotImplementedError


class MockLinkedInAdapter(LinkedInAdapter):
    def publish_post(self, body: str, image_bytes: bytes | None = None, image_mime: str | None = None) -> PublishResult:
        if not body or not body.strip():
            return PublishResult(False, None, "Content body is empty.")
        return PublishResult(True, "mock-post-001", "Mock publish succeeded; no external LinkedIn action was made.")


class OfficialLinkedInAdapter(LinkedInAdapter):
    def __init__(self, access_token: str, member_sub: str):
        self.access_token = access_token
        self.member_sub = member_sub

    def publish_post(self, body: str, image_bytes: bytes | None = None, image_mime: str | None = None) -> PublishResult:
        if not body or not body.strip():
            return PublishResult(False, None, "Content body is empty.")

        base = (settings.linkedin_api_base_url or "https://api.linkedin.com").rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": settings.linkedin_api_version,
        }
        uploaded_image_urn = None
        payload = {
            "author": f"urn:li:person:{self.member_sub}",
            "commentary": body.strip(),
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        if image_bytes:
            if image_mime not in {"image/jpeg", "image/png", "image/gif"}:
                return PublishResult(False, None, "Only JPEG, PNG, or GIF images are supported.")

            init_url = f"{base}/rest/images?action=initializeUpload"
            init_payload = {
                "initializeUploadRequest": {
                    "owner": f"urn:li:person:{self.member_sub}",
                }
            }
            init_request = urllib.request.Request(
                init_url,
                data=json.dumps(init_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(init_request, timeout=20) as response:
                    init_data = json.loads(response.read().decode("utf-8"))
                upload = init_data.get("value") or {}
                upload_url = upload.get("uploadUrl")
                image_urn = upload.get("image")
                if not upload_url or not image_urn:
                    return PublishResult(False, None, "LinkedIn did not return a usable image upload URL.")

                upload_request = urllib.request.Request(
                    upload_url,
                    data=image_bytes,
                    headers={"Content-Type": image_mime},
                    method="PUT",
                )
                with urllib.request.urlopen(upload_request, timeout=30) as response:
                    if response.status not in {200, 201}:
                        return PublishResult(False, None, f"LinkedIn image upload failed ({response.status}).")

                payload["content"] = {
                    "media": {
                        "id": image_urn,
                        "altText": "",
                    }
                }
                uploaded_image_urn = image_urn
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                return PublishResult(False, None, f"LinkedIn image upload was rejected ({exc.code}): {detail[:500]}")
            except Exception as exc:
                return PublishResult(False, None, f"LinkedIn image upload failed: {exc}")

        url = f"{base}/rest/posts"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                external_id = response.headers.get("x-restli-id")
                suffix = " with image." if image_bytes else "."
                return PublishResult(True, external_id, f"Published to LinkedIn through the official Posts API{suffix}", uploaded_image_urn)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return PublishResult(False, None, f"LinkedIn API rejected the post ({exc.code}): {detail[:500]}")
        except Exception as exc:
            return PublishResult(False, None, f"LinkedIn API request failed: {exc}")
