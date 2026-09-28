"""Vast.ai adapter over the public HTTP API, using only urllib.

Credentials come from the VAST_API_KEY environment variable (or an injected
value) and are sent only in the Authorization header — never on argv, never
logged. Set VAST_API_URL to point at a mock during testing.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List, Optional

from ..models import Instance
from .base import Provider, ProviderError

DEFAULT_API_URL = "https://console.vast.ai/api/v0"


class VastProvider(Provider):
    name = "vast"

    def __init__(
        self,
        api_key: Optional[str] = None,
        image: Optional[str] = None,
        disk_gb: int = 32,
        onstart: str = "",
        env: Optional[dict] = None,
        timeout: int = 30,
        api_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("VAST_API_KEY", "")
        if not self.api_key:
            raise ProviderError(
                "VAST_API_KEY is not set. Get a key at your provider account "
                "page and export it before running."
            )
        self.image = image or os.environ.get(
            "SPOTSCALE_WORKER_IMAGE", "pytorch/pytorch:latest"
        )
        self.disk_gb = disk_gb
        self.onstart = onstart
        self.env = dict(env or {})
        self.timeout = timeout
        self.api_url = (api_url or os.environ.get("VAST_API_URL") or DEFAULT_API_URL).rstrip("/")

    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{self.api_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:
                pass
            err = ProviderError(f"vast {method} {path} -> HTTP {e.code}: {detail}")
            err.status_code = e.code
            raise err
        except urllib.error.URLError as e:
            raise ProviderError(f"vast {method} {path} failed: {e.reason}")
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ProviderError(f"vast {method} {path}: non-JSON response")

    # ------------------------------------------------------------------ #
    def _search_offers(self, gpu: str, max_price: float) -> List[dict]:
        """Find rentable on-demand offers for `gpu` at or under `max_price`.

        NOTE: this adapter rents **on-demand** instances today (``"type":
        "on-demand"`` below). Interruptible/bid ("spot") rentals are not yet
        wired up — the cost cap and reaper still apply either way. See the
        README for the roadmap.
        """
        query = {
            "q": {
                "rentable": {"eq": True},
                "dph_total": {"lte": max_price},
                "type": "on-demand",
                "order": [["dph_total", "asc"]],
                "limit": 20,
            }
        }
        if gpu:
            query["q"]["gpu_name"] = {"eq": gpu}
        resp = self._request("PUT", "/search/asks/", query)
        offers = resp.get("offers", []) or []
        # Defensive client-side filter/sort — never trust the server to have
        # honoured the price bound.
        offers = [o for o in offers if float(o.get("dph_total") or 0) <= max_price]
        offers.sort(key=lambda o: float(o.get("dph_total") or 1e9))
        return offers

    def spin(self, gpu: str, max_price: float, label: str = "") -> Instance:
        offers = self._search_offers(gpu, max_price)
        if not offers:
            raise ProviderError(
                f"no rentable {gpu or 'GPU'} offer at or below ${max_price:.4f}/hr"
            )
        offer = offers[0]
        offer_id = offer.get("id") or offer.get("ask_contract_id")
        if offer_id is None:
            raise ProviderError("offer had no id")

        create_body = {
            "client_id": "me",
            "image": self.image,
            "disk": self.disk_gb,
            "label": label,
            "onstart": self.onstart,
            "env": self.env,
            "price": max_price,
            "runtype": "ssh",
        }
        resp = self._request("PUT", f"/asks/{offer_id}/", create_body)
        if not resp.get("success", False):
            raise ProviderError(f"vast create rejected: {resp}")
        contract_id = resp.get("new_contract")
        if contract_id is None:
            # Exited "successfully" but created nothing — treat as failure so the
            # caller marks the worker failed instead of leaking a phantom.
            raise ProviderError(f"vast create returned no contract id: {resp}")

        return Instance(
            id=str(contract_id),
            status="starting",
            gpu=str(offer.get("gpu_name") or gpu),
            price_per_hour=float(offer.get("dph_total") or 0.0),
            label=label,
            uptime_hours=0.0,
        )

    def list(self) -> List[Instance]:
        resp = self._request("GET", "/instances/")
        out: List[Instance] = []
        for i in resp.get("instances", []) or []:
            out.append(
                Instance(
                    id=str(i.get("id")),
                    status=str(i.get("actual_status") or i.get("cur_state") or "").lower(),
                    gpu=str(i.get("gpu_name") or ""),
                    price_per_hour=float(i.get("dph_total") or 0.0),
                    label=str(i.get("label") or ""),
                    uptime_hours=round(float(i.get("duration") or 0.0) / 3600.0, 2),
                    ip=str(i.get("public_ipaddr") or ""),
                )
            )
        return out

    def kill(self, instance_id: str) -> bool:
        # Base contract: return True if the instance is gone OR already gone. A
        # 404 means the instance no longer exists, which satisfies "is it gone?" —
        # so we swallow it and report success. Any other error (auth, network,
        # 5xx) still propagates so callers see a genuine failure.
        try:
            resp = self._request("DELETE", f"/instances/{instance_id}/")
        except ProviderError as e:
            if getattr(e, "status_code", None) == 404:
                return True
            raise
        # Vast returns {"success": true}; an empty body also counts as done.
        return bool(resp.get("success", True))

