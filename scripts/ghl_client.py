"""Minimal GoHighLevel API v2 client (stdlib only).

Auth uses a sub-account Private Integration token. See .env.example.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_config(path=ROOT / "ghl" / "config.json"):
    return json.loads(Path(path).read_text())


class GHLError(RuntimeError):
    pass


class GHLClient:
    def __init__(self, token=None, location_id=None, dry_run=False):
        load_env()
        self.token = token or os.environ.get("GHL_PRIVATE_TOKEN", "")
        self.location_id = location_id or os.environ.get("GHL_LOCATION_ID", "")
        self.dry_run = dry_run
        if not dry_run and not (self.token and self.location_id):
            raise GHLError("Set GHL_PRIVATE_TOKEN and GHL_LOCATION_ID in .env (see .env.example)")

    def request(self, method, path, body=None, query=None, retries=4):
        url = BASE_URL + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        if self.dry_run:
            print(f"[dry-run] {method} {url} {json.dumps(body) if body else ''}")
            return {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Version": API_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise GHLError(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')}") from e

    # --- location setup ---
    def custom_fields(self):
        return self.request("GET", f"/locations/{self.location_id}/customFields").get("customFields", [])

    def create_custom_field(self, name, data_type):
        return self.request("POST", f"/locations/{self.location_id}/customFields",
                            {"name": name, "dataType": data_type, "model": "contact"})

    def tags(self):
        return self.request("GET", f"/locations/{self.location_id}/tags").get("tags", [])

    def create_tag(self, name):
        return self.request("POST", f"/locations/{self.location_id}/tags", {"name": name})

    def custom_values(self):
        return self.request("GET", f"/locations/{self.location_id}/customValues").get("customValues", [])

    def create_custom_value(self, name, value):
        return self.request("POST", f"/locations/{self.location_id}/customValues", {"name": name, "value": value})

    def pipelines(self):
        return self.request("GET", "/opportunities/pipelines",
                            query={"locationId": self.location_id}).get("pipelines", [])

    # --- leads ---
    def upsert_contact(self, contact):
        body = dict(contact, locationId=self.location_id)
        return self.request("POST", "/contacts/upsert", body).get("contact", {})

    def create_opportunity(self, pipeline_id, stage_id, contact_id, name, value):
        return self.request("POST", "/opportunities/", {
            "locationId": self.location_id,
            "pipelineId": pipeline_id,
            "pipelineStageId": stage_id,
            "contactId": contact_id,
            "name": name,
            "status": "open",
            "monetaryValue": value,
        })
