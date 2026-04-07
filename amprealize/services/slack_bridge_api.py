"""FastAPI routes for the Slack bridge webhooks (AMPREALIZE-602).

Exposes:
    POST /v1/integrations/slack/events    — Slack Events API webhook
    POST /v1/integrations/slack/commands  — Slash command handler (/amprealize)

All inbound requests are verified via Slack signing secret before dispatch.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from amprealize.services.slack_bridge import (
    SlackBridgeService,
    SlackVerificationError,
)

logger = logging.getLogger(__name__)


def create_slack_bridge_routes(
    slack_bridge: SlackBridgeService,
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """Create a FastAPI router for Slack bridge webhook endpoints.

    Args:
        slack_bridge: Initialized SlackBridgeService instance.
        tags: Optional OpenAPI tags.

    Returns:
        APIRouter with Slack webhook routes.
    """
    router = APIRouter(tags=tags or ["integrations", "slack"])

    # ------------------------------------------------------------------
    # Slack Events API endpoint
    # ------------------------------------------------------------------

    @router.post(
        "/v1/integrations/slack/events",
        summary="Slack Events API webhook",
        description="Receives events from Slack (messages, reactions, etc.).",
        response_model=None,
    )
    async def slack_events(
        request: Request,
        x_slack_request_timestamp: Optional[str] = Header(None),
        x_slack_signature: Optional[str] = Header(None),
    ) -> Response:
        body = await request.body()

        # Verify request signature
        if x_slack_request_timestamp and x_slack_signature:
            try:
                slack_bridge.verify_request(
                    timestamp=x_slack_request_timestamp,
                    signature=x_slack_signature,
                    body=body,
                )
            except SlackVerificationError as e:
                logger.warning("Slack signature verification failed: %s", e)
                raise HTTPException(status_code=401, detail="Invalid signature")
        else:
            raise HTTPException(status_code=401, detail="Missing Slack signature headers")

        # Parse the event payload
        try:
            payload: Dict[str, Any] = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Handle URL verification challenge immediately
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge", "")
            return JSONResponse(
                content={"challenge": challenge},
                headers={"Content-Type": "application/json"},
            )

        # Dispatch to bridge service
        result = await slack_bridge.handle_event(payload)

        if result is not None:
            return JSONResponse(content=result)

        # Slack expects 200 OK within 3 seconds
        return Response(status_code=200)

    # ------------------------------------------------------------------
    # Slack Slash Commands endpoint
    # ------------------------------------------------------------------

    @router.post(
        "/v1/integrations/slack/commands",
        summary="Slack slash command handler",
        description="Handles /amprealize slash commands from Slack.",
        response_model=None,
    )
    async def slack_commands(
        request: Request,
        x_slack_request_timestamp: Optional[str] = Header(None),
        x_slack_signature: Optional[str] = Header(None),
    ) -> Response:
        body = await request.body()

        # Verify request signature
        if x_slack_request_timestamp and x_slack_signature:
            try:
                slack_bridge.verify_request(
                    timestamp=x_slack_request_timestamp,
                    signature=x_slack_signature,
                    body=body,
                )
            except SlackVerificationError as e:
                logger.warning("Slack command signature verification failed: %s", e)
                raise HTTPException(status_code=401, detail="Invalid signature")
        else:
            raise HTTPException(status_code=401, detail="Missing Slack signature headers")

        # Parse form-encoded slash command payload
        form_data = await request.form()
        command_payload: Dict[str, Any] = dict(form_data)

        # Dispatch to bridge service
        result = await slack_bridge.handle_slash_command(command_payload)

        return JSONResponse(content=result)

    return router
