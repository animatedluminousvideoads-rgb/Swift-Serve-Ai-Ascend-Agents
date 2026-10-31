"""Minimal GoHighLevel API v2 client (services.leadconnectorhq.com).

Authenticates with a sub-account Private Integration Token. Endpoint shapes
follow GoHighLevel's published OpenAPI specs (github.com/GoHighLevel/highlevel-api-docs).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://services.leadconnectorhq.com"
V_DEFAULT = "2021-07-28"   # contacts, opportunities, locations, workflows
V_LEGACY = "2021-04-15"    # voice-ai, calendars, conversations


class GHLError(Exception):
    def __init__(self, status: int, method: str, path: str, body: str):
        super().__init__(f"GHL {method} {path} failed with HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class GHLClient:
    def __init__(
        self,
        token: str,
        location_id: str,
        session: requests.Session | None = None,
        max_retries: int = 4,
        sleep=time.sleep,
    ):
        self.location_id = location_id
        self.http = session or requests.Session()
        self.http.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.max_retries = max_retries
        self._sleep = sleep

    # -- transport -----------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        version: str = V_DEFAULT,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = BASE_URL + path
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.http.request(
                    method, url, params=params, json=json, headers={"Version": version}, timeout=30
                )
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    self._sleep(2 ** (attempt + 1))
                    continue
                raise GHLError(0, method, path, f"network error: {exc}") from exc
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.max_retries:
                    wait = float(resp.headers.get("Retry-After") or 2 ** (attempt + 1))
                    log.warning("GHL %s %s -> %s, retrying in %.0fs", method, path, resp.status_code, wait)
                    self._sleep(min(wait, 60))
                    continue
            if resp.status_code >= 400:
                raise GHLError(resp.status_code, method, path, resp.text)
            return resp.json() if resp.content else {}
        raise AssertionError("unreachable")

    # -- contacts ------------------------------------------------------------------

    def upsert_contact(self, fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Create or update by phone/email. Never pass `tags` here: upsert overwrites them."""
        body = {"locationId": self.location_id, **fields}
        body.pop("tags", None)
        data = self.request("POST", "/contacts/upsert", json=body)
        return data.get("contact", {}), bool(data.get("new"))

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        return self.request("GET", f"/contacts/{contact_id}").get("contact", {})

    def update_contact(self, contact_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request("PUT", f"/contacts/{contact_id}", json=fields).get("contact", {})

    def add_tags(self, contact_id: str, tags: list[str]) -> None:
        if tags:
            self.request("POST", f"/contacts/{contact_id}/tags", json={"tags": tags})

    def remove_tags(self, contact_id: str, tags: list[str]) -> None:
        if tags:
            self.request("DELETE", f"/contacts/{contact_id}/tags", json={"tags": tags})

    def list_notes(self, contact_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/contacts/{contact_id}/notes").get("notes", [])

    def add_note(self, contact_id: str, body: str) -> None:
        self.request("POST", f"/contacts/{contact_id}/notes", json={"body": body})

    def create_task(self, contact_id: str, title: str, body: str, due_iso: str) -> None:
        self.request(
            "POST",
            f"/contacts/{contact_id}/tasks",
            json={"title": title, "body": body, "dueDate": due_iso, "completed": False},
        )

    def add_to_workflow(self, contact_id: str, workflow_id: str) -> None:
        self.request("POST", f"/contacts/{contact_id}/workflow/{workflow_id}", json={})

    # -- custom fields -------------------------------------------------------------

    def list_custom_fields(self, model: str = "contact") -> list[dict[str, Any]]:
        data = self.request(
            "GET", f"/locations/{self.location_id}/customFields", params={"model": model}
        )
        return data.get("customFields", [])

    def create_custom_field(self, name: str, data_type: str = "TEXT", model: str = "contact") -> dict[str, Any]:
        data = self.request(
            "POST",
            f"/locations/{self.location_id}/customFields",
            json={"name": name, "dataType": data_type, "model": model},
        )
        return data.get("customField", data)

    # -- pipelines / opportunities -------------------------------------------------

    def list_pipelines(self) -> list[dict[str, Any]]:
        data = self.request("GET", "/opportunities/pipelines", params={"locationId": self.location_id})
        return data.get("pipelines", [])

    def create_opportunity(self, fields: dict[str, Any]) -> dict[str, Any]:
        body = {"locationId": self.location_id, **fields}
        return self.request("POST", "/opportunities/", json=body).get("opportunity", {})

    def update_opportunity(self, opportunity_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request("PUT", f"/opportunities/{opportunity_id}", json=fields).get("opportunity", {})

    def search_opportunities(self, **filters: Any) -> list[dict[str, Any]]:
        """filters: pipeline_id, pipeline_stage_id, contact_id, status, limit, page."""
        params = {"location_id": self.location_id, "limit": 100, **filters}
        return self.request("GET", "/opportunities/search", params=params).get("opportunities", [])

    # -- workflows / calendars -----------------------------------------------------

    def list_workflows(self) -> list[dict[str, Any]]:
        return self.request("GET", "/workflows/", params={"locationId": self.location_id}).get("workflows", [])

    def list_calendars(self) -> list[dict[str, Any]]:
        data = self.request("GET", "/calendars/", version=V_LEGACY, params={"locationId": self.location_id})
        return data.get("calendars", [])

    # -- voice ai ------------------------------------------------------------------

    def list_voice_agents(self, query: str = "") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"locationId": self.location_id, "page": 1, "pageSize": 50}
        if query:
            params["query"] = query
        return self.request("GET", "/voice-ai/agents", version=V_LEGACY, params=params).get("agents", [])

    def get_voice_agent(self, agent_id: str) -> dict[str, Any]:
        return self.request(
            "GET", f"/voice-ai/agents/{agent_id}", version=V_LEGACY, params={"locationId": self.location_id}
        )

    def create_voice_agent(self, fields: dict[str, Any]) -> dict[str, Any]:
        body = {"locationId": self.location_id, **fields}
        return self.request("POST", "/voice-ai/agents", version=V_LEGACY, json=body)

    def patch_voice_agent(self, agent_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "PATCH",
            f"/voice-ai/agents/{agent_id}",
            version=V_LEGACY,
            params={"locationId": self.location_id},
            json=fields,
        )

    def create_voice_action(self, agent_id: str, action_type: str, name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        body = {
            "agentId": agent_id,
            "locationId": self.location_id,
            "actionType": action_type,
            "name": name,
            "actionParameters": parameters,
        }
        return self.request("POST", "/voice-ai/actions", version=V_LEGACY, json=body)

    def list_call_logs(self, agent_id: str, page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        params = {
            "locationId": self.location_id,
            "agentId": agent_id,
            "callType": "LIVE",
            "sortBy": "createdAt",
            "sort": "descend",
            "page": page,
            "pageSize": page_size,
        }
        return self.request("GET", "/voice-ai/dashboard/call-logs", version=V_LEGACY, params=params).get(
            "callLogs", []
        )

    # -- conversations -------------------------------------------------------------

    def send_sms(self, contact_id: str, message: str) -> dict[str, Any]:
        body = {"type": "SMS", "contactId": contact_id, "message": message}
        return self.request("POST", "/conversations/messages", version=V_LEGACY, json=body)

    def send_email(self, contact_id: str, subject: str, html: str) -> dict[str, Any]:
        body = {"type": "Email", "contactId": contact_id, "subject": subject, "html": html}
        return self.request("POST", "/conversations/messages", version=V_LEGACY, json=body)
