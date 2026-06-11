"""Webhook dispatcher for execution gate events.

Sends HTTP POST callbacks to registered webhook URLs when gate events occur.
Supports HMAC-SHA256 signing for payload verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Signing secret for HMAC verification
_SIGNING_SECRET = os.environ.get("AMPREALIZE_WEBHOOK_SIGNING_SECRET", "")


@dataclass
class WebhookDelivery:
    """Record of a webhook delivery attempt."""
    url: str
    payload: Dict[str, Any]
    status_code: Optional[int] = None
    error: Optional[str] = None
    attempt: int = 1
    delivered_at: Optional[float] = None


class WebhookDispatcher:
    """Dispatches webhook callbacks for execution events.

    Sends HTTP POST requests to callback URLs with retry logic
    and HMAC signing.

    Usage:
        dispatcher = WebhookDispatcher()
        await dispatcher.dispatch(
            url="https://example.com/hooks/amprealize",
            event="gate.waiting",
            payload={...},
        )
    """

    def __init__(
        self,
        signing_secret: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: float = 10.0,
        backoff_base: float = 2.0,
    ):
        self._signing_secret = signing_secret or _SIGNING_SECRET
        self._max_retries = max_retries
        self._timeout = timeout_seconds
        self._backoff_base = backoff_base

    def _sign_payload(self, payload_bytes: bytes, timestamp: str) -> str:
        """Generate HMAC-SHA256 signature for payload verification.

        Signature format: sha256=<hex_digest>
        Signed data: <timestamp>.<payload_body>
        """
        if not self._signing_secret:
            return ""
        signed_data = f"{timestamp}.".encode() + payload_bytes
        signature = hmac.new(
            self._signing_secret.encode(),
            signed_data,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"

    async def dispatch(
        self,
        url: str,
        event: str,
        payload: Dict[str, Any],
    ) -> WebhookDelivery:
        """Dispatch a webhook to the given URL.

        Args:
            url: The callback URL to POST to.
            event: Event type (e.g. "gate.waiting", "gate.clarification_needed").
            payload: The event payload.

        Returns:
            WebhookDelivery record with the result.
        """
        envelope = {
            "event": event,
            "timestamp": time.time(),
            **payload,
        }
        body = json.dumps(envelope, default=str).encode()
        timestamp = str(int(time.time()))
        signature = self._sign_payload(body, timestamp)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Amprealize-Webhooks/1.0",
            "X-Amprealize-Event": event,
            "X-Amprealize-Timestamp": timestamp,
        }
        if signature:
            headers["X-Amprealize-Signature"] = signature

        delivery = WebhookDelivery(url=url, payload=envelope)

        for attempt in range(1, self._max_retries + 1):
            delivery.attempt = attempt
            try:
                import httpx

                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, content=body, headers=headers)
                    delivery.status_code = resp.status_code
                    delivery.delivered_at = time.time()

                    if 200 <= resp.status_code < 300:
                        logger.info(
                            f"Webhook delivered: {event} → {url} "
                            f"(status={resp.status_code}, attempt={attempt})"
                        )
                        return delivery
                    elif resp.status_code >= 500:
                        # Server error — retry
                        logger.warning(
                            f"Webhook server error: {event} → {url} "
                            f"(status={resp.status_code}, attempt={attempt})"
                        )
                    else:
                        # Client error (4xx) — don't retry
                        logger.warning(
                            f"Webhook client error: {event} → {url} "
                            f"(status={resp.status_code}, attempt={attempt})"
                        )
                        return delivery

            except ImportError:
                delivery.error = "httpx not installed"
                logger.error("httpx not installed — cannot dispatch webhooks")
                return delivery
            except Exception as exc:
                delivery.error = str(exc)
                logger.warning(
                    f"Webhook dispatch failed: {event} → {url} "
                    f"(error={exc}, attempt={attempt})"
                )

            # Exponential backoff before retry
            if attempt < self._max_retries:
                wait = self._backoff_base ** (attempt - 1)
                await asyncio.sleep(wait)

        logger.error(
            f"Webhook delivery failed after {self._max_retries} attempts: "
            f"{event} → {url}"
        )
        return delivery

    async def dispatch_many(
        self,
        urls: List[str],
        event: str,
        payload: Dict[str, Any],
    ) -> List[WebhookDelivery]:
        """Dispatch a webhook to multiple URLs concurrently."""
        tasks = [self.dispatch(url, event, payload) for url in urls]
        return await asyncio.gather(*tasks)
