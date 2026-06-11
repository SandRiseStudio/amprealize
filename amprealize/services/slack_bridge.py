"""Slack bridge service for bidirectional messaging (AMPREALIZE-566, Phase 7).

Provides:
- Slack Events API webhook verification + dispatch
- Outbound relay: Amprealize → Slack via chat.postMessage
- Inbound relay: Slack → Amprealize via ConversationService
- Thread correlation: Slack thread_ts ↔ Amprealize parent_id
- Reaction sync: emoji add/remove in both directions
- Slash command handler for /amprealize connect

Security:
- All incoming webhooks verified via Slack signing secret (HMAC-SHA256)
- Bot tokens never logged or exposed in error responses
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from amprealize.config.settings import SlackConfig
from amprealize.conversation_contracts import (
    ActorType,
    ConversationScope,
    ExternalBinding,
    ExternalProvider,
    Message,
    MessageType,
)
from amprealize.conversation_event_hub import (
    EVENT_MESSAGE_NEW,
    EVENT_REACTION_ADDED,
    EVENT_REACTION_REMOVED,
)
from amprealize.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

# Slack API base URL
SLACK_API_BASE = "https://slack.com/api"

# Maximum age of a Slack request before we reject it (5 minutes)
MAX_REQUEST_AGE_SECONDS = 300

# Slack signing version
SIGNING_VERSION = "v0"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SlackMessageIdentifier:
    """Cross-reference between an Amprealize message and its Slack counterpart."""
    amprealize_message_id: str
    slack_channel_id: str
    slack_ts: str
    slack_thread_ts: Optional[str] = None


@dataclass
class SlackUserMapping:
    """Maps a Slack user ID to an Amprealize actor ID."""
    slack_user_id: str
    amprealize_actor_id: str
    display_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SlackBridgeError(Exception):
    """Base exception for Slack bridge operations."""


class SlackVerificationError(SlackBridgeError):
    """Raised when Slack request signature verification fails."""


class SlackAPIError(SlackBridgeError):
    """Raised when a Slack API call fails."""

    def __init__(self, method: str, error: str, detail: Optional[str] = None):
        self.method = method
        self.error = error
        self.detail = detail
        super().__init__(f"Slack API {method} failed: {error}")


# ---------------------------------------------------------------------------
# SlackBridgeService
# ---------------------------------------------------------------------------


class SlackBridgeService:
    """Bidirectional bridge between Amprealize conversations and Slack channels.

    Usage::

        bridge = SlackBridgeService(
            config=slack_config,
            conversation_service=conversation_service,
        )
        # Verify + dispatch inbound webhook
        bridge.verify_request(timestamp, signature, body)
        await bridge.handle_event(event_payload)

        # Outbound relay
        await bridge.relay_to_slack(message, binding)
    """

    def __init__(
        self,
        config: SlackConfig,
        conversation_service: ConversationService,
        http_client: Optional[httpx.AsyncClient] = None,
        event_hub: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._conversation = conversation_service
        self._http: Optional[httpx.AsyncClient] = http_client
        self._event_hub = event_hub
        # In-memory thread correlation cache: amprealize_message_id → slack_ts
        self._thread_map: Dict[str, str] = {}
        # Reverse map: slack_channel:slack_ts → amprealize_message_id
        self._reverse_thread_map: Dict[str, str] = {}
        # Guard against echo loops: set of slack_ts we just posted
        self._echo_guard: Dict[str, float] = {}
        # Agent display override registry: agent_id → (name, icon)
        self._agent_display: Dict[str, tuple] = {}
        # Background subscription task
        self._subscription_task: Optional[asyncio.Task] = None
        # Subscribed conversation queues for cleanup
        self._subscribed_queues: Dict[str, asyncio.Queue] = {}

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self) -> None:
        """Close the HTTP client and stop event hub subscription."""
        await self.stop_outbound_subscription()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Agent display overrides (AMPREALIZE-603)
    # ------------------------------------------------------------------

    def register_agent_display(
        self, agent_id: str, name: str, icon: str = ":robot_face:"
    ) -> None:
        """Register display overrides for an agent's Slack messages."""
        self._agent_display[agent_id] = (name, icon)

    def resolve_agent_display(
        self, sender_id: str,
    ) -> tuple:
        """Resolve display name + icon for an agent sender.

        Falls back to deriving a name from the sender_id and using the
        default bot icon from config.
        """
        if sender_id in self._agent_display:
            return self._agent_display[sender_id]
        # Derive a readable name: "agent:code-reviewer" → "Code Reviewer"
        label = sender_id
        if ":" in label:
            label = label.split(":", 1)[1]
        name = label.replace("-", " ").replace("_", " ").title()
        return (name, self._config.default_bot_icon)

    # ------------------------------------------------------------------
    # Outbound event hub subscription (AMPREALIZE-603)
    # ------------------------------------------------------------------

    async def start_outbound_subscription(self, conversation_ids: Optional[List[str]] = None) -> None:
        """Subscribe to the ConversationEventHub for outbound relay.

        If *conversation_ids* is ``None``, discovers all bound conversations
        and subscribes to each.  The subscription runs as a background task.
        """
        if self._event_hub is None:
            logger.warning("No event hub configured — outbound relay disabled")
            return

        if conversation_ids is None:
            # Discover all active slack bindings
            conversation_ids = self._discover_bound_conversations()

        for cid in conversation_ids:
            await self._subscribe_conversation(cid)

        logger.info(
            "Slack outbound relay started for %d conversations", len(conversation_ids)
        )

    async def subscribe_conversation(self, conversation_id: str) -> None:
        """Add a single conversation to the outbound subscription."""
        await self._subscribe_conversation(conversation_id)

    async def _subscribe_conversation(self, conversation_id: str) -> None:
        """Create an event hub queue subscription for a conversation."""
        if conversation_id in self._subscribed_queues:
            return
        if self._event_hub is None:
            return

        queue = await self._event_hub.subscribe_queue(conversation_id)
        self._subscribed_queues[conversation_id] = queue

        # Spawn a consumer task
        task = asyncio.get_running_loop().create_task(
            self._consume_queue(conversation_id, queue)
        )
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _consume_queue(self, conversation_id: str, queue: asyncio.Queue) -> None:
        """Consume events from a queue and relay to Slack."""
        try:
            while True:
                event = await queue.get()
                event_type = event.get("type", "")
                payload = event.get("payload", {})

                try:
                    await self.on_amprealize_event(event_type, conversation_id, payload)
                except Exception:
                    logger.exception(
                        "Error relaying event %s for conversation %s",
                        event_type, conversation_id,
                    )
        except asyncio.CancelledError:
            pass
        finally:
            if self._event_hub:
                await self._event_hub.unsubscribe_queue(
                    queue, conversation_id=conversation_id
                )
            self._subscribed_queues.pop(conversation_id, None)

    async def stop_outbound_subscription(self) -> None:
        """Stop all outbound relay subscriptions."""
        for cid, queue in list(self._subscribed_queues.items()):
            if self._event_hub:
                await self._event_hub.unsubscribe_queue(queue, conversation_id=cid)
        self._subscribed_queues.clear()

    def _discover_bound_conversations(self) -> List[str]:
        """Discover conversation IDs with active Slack bindings.

        Queries the binding table at startup so the outbound relay covers
        all pre-existing channel↔conversation mappings.
        """
        if self._conversation is None:
            return []
        try:
            bindings = self._conversation.list_all_active_bindings(
                ExternalProvider.SLACK
            )
            return [b.conversation_id for b in bindings]
        except Exception:
            logger.exception("Failed to discover bound conversations at startup")
            return []

    # ------------------------------------------------------------------
    # Slack request verification (security-critical)
    # ------------------------------------------------------------------

    def verify_request(self, timestamp: str, signature: str, body: bytes) -> None:
        """Verify a Slack request signature using the signing secret.

        Raises SlackVerificationError if verification fails.
        See: https://api.slack.com/authentication/verifying-requests-from-slack
        """
        if not self._config.signing_secret:
            raise SlackVerificationError("Slack signing secret not configured")

        # Reject stale requests (replay protection)
        try:
            ts = int(timestamp)
        except (ValueError, TypeError):
            raise SlackVerificationError("Invalid timestamp")

        if abs(time.time() - ts) > MAX_REQUEST_AGE_SECONDS:
            raise SlackVerificationError("Request timestamp too old")

        # Compute expected signature
        sig_basestring = f"{SIGNING_VERSION}:{timestamp}:{body.decode('utf-8')}"
        computed = (
            f"{SIGNING_VERSION}="
            + hmac.new(
                self._config.signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )

        if not hmac.compare_digest(computed, signature):
            raise SlackVerificationError("Signature mismatch")

    # ------------------------------------------------------------------
    # Slack API helpers
    # ------------------------------------------------------------------

    async def _slack_api(
        self,
        method: str,
        payload: Dict[str, Any],
        *,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call a Slack Web API method.

        Returns the parsed JSON response.
        Raises SlackAPIError on failure.
        """
        bot_token = token or self._config.bot_token
        if not bot_token:
            raise SlackAPIError(method, "no_token", "Bot token not configured")

        http = await self._get_http()
        resp = await http.post(
            f"{SLACK_API_BASE}/{method}",
            json=payload,
            headers={"Authorization": f"Bearer {bot_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            raise SlackAPIError(
                method,
                data.get("error", "unknown_error"),
                data.get("response_metadata", {}).get("messages", [None])[0] if data.get("response_metadata") else None,
            )

        return data

    async def post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        username: Optional[str] = None,
        icon_emoji: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Post a message to a Slack channel.

        Returns the Slack API response including the message ``ts``.
        """
        payload: Dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks
        if username:
            payload["username"] = username
            payload["icon_emoji"] = icon_emoji or self._config.default_bot_icon
        return await self._slack_api("chat.postMessage", payload)

    async def add_slack_reaction(self, channel: str, timestamp: str, emoji: str) -> None:
        """Add a reaction to a Slack message."""
        try:
            await self._slack_api("reactions.add", {
                "channel": channel,
                "timestamp": timestamp,
                "name": emoji.strip(":"),
            })
        except SlackAPIError as e:
            if e.error != "already_reacted":
                raise

    async def remove_slack_reaction(self, channel: str, timestamp: str, emoji: str) -> None:
        """Remove a reaction from a Slack message."""
        try:
            await self._slack_api("reactions.remove", {
                "channel": channel,
                "timestamp": timestamp,
                "name": emoji.strip(":"),
            })
        except SlackAPIError as e:
            if e.error != "no_reaction":
                raise

    # ------------------------------------------------------------------
    # Echo guard (prevent relay loops)
    # ------------------------------------------------------------------

    def _mark_echo(self, slack_ts: str) -> None:
        """Mark a Slack ts as one we just posted (to ignore our own echoes)."""
        self._echo_guard[slack_ts] = time.monotonic()
        # Prune old entries (older than 60s)
        cutoff = time.monotonic() - 60
        stale = [k for k, v in self._echo_guard.items() if v < cutoff]
        for k in stale:
            del self._echo_guard[k]

    def _is_echo(self, slack_ts: str) -> bool:
        """Check if a Slack ts was recently posted by us."""
        return slack_ts in self._echo_guard

    # ------------------------------------------------------------------
    # Thread correlation
    # ------------------------------------------------------------------

    def store_thread_mapping(
        self, amprealize_message_id: str, slack_channel: str, slack_ts: str
    ) -> None:
        """Store a bidirectional mapping between an Amprealize message and Slack ts."""
        self._thread_map[amprealize_message_id] = slack_ts
        self._reverse_thread_map[f"{slack_channel}:{slack_ts}"] = amprealize_message_id

    def get_slack_ts(self, amprealize_message_id: str) -> Optional[str]:
        """Get the Slack ts for an Amprealize message."""
        return self._thread_map.get(amprealize_message_id)

    def get_amprealize_message_id(self, slack_channel: str, slack_ts: str) -> Optional[str]:
        """Get the Amprealize message ID for a Slack ts."""
        return self._reverse_thread_map.get(f"{slack_channel}:{slack_ts}")

    # ------------------------------------------------------------------
    # Outbound relay: Amprealize → Slack
    # ------------------------------------------------------------------

    async def relay_to_slack(
        self,
        message: Message,
        binding: ExternalBinding,
        *,
        agent_name: Optional[str] = None,
        agent_icon: Optional[str] = None,
    ) -> Optional[str]:
        """Relay an Amprealize message to the bound Slack channel.

        Returns the Slack message ts on success, None on failure.
        """
        # Build display overrides for agent messages
        username = None
        icon = None
        if message.sender_type == ActorType.AGENT:
            if agent_name:
                username = agent_name
                icon = agent_icon or self._config.default_bot_icon
            else:
                username, icon = self.resolve_agent_display(message.sender_id)
        elif message.sender_type == ActorType.SYSTEM:
            username = "Amprealize System"
            icon = ":gear:"

        # Determine thread_ts for threaded replies
        thread_ts = None
        if message.parent_id:
            thread_ts = self.get_slack_ts(message.parent_id)

        # Format content
        text = message.content or ""
        blocks = self._format_message_blocks(message)

        try:
            response = await self.post_message(
                channel=binding.external_channel_id,
                text=text,
                thread_ts=thread_ts,
                blocks=blocks if blocks else None,
                username=username,
                icon_emoji=icon,
            )

            slack_ts = response.get("ts")
            if slack_ts:
                self._mark_echo(slack_ts)
                self.store_thread_mapping(
                    message.id, binding.external_channel_id, slack_ts
                )
            return slack_ts

        except SlackAPIError:
            logger.exception("Failed to relay message %s to Slack", message.id)
            return None

    def _format_message_blocks(self, message: Message) -> Optional[List[Dict[str, Any]]]:
        """Convert an Amprealize message to Slack Block Kit blocks.

        Returns None for plain text messages (Slack will use the text field).
        """
        if message.message_type == MessageType.TEXT:
            return None

        if message.message_type == MessageType.CODE_BLOCK:
            return [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{message.content or ''}```"},
                }
            ]

        if message.message_type in (
            MessageType.STATUS_CARD,
            MessageType.BLOCKER_CARD,
            MessageType.PROGRESS_CARD,
            MessageType.RUN_SUMMARY,
        ):
            payload = message.structured_payload or {}
            title = payload.get("title", message.message_type.value.replace("_", " ").title())
            body = payload.get("body", message.content or "")
            emoji_map = {
                MessageType.STATUS_CARD: ":large_blue_circle:",
                MessageType.BLOCKER_CARD: ":red_circle:",
                MessageType.PROGRESS_CARD: ":chart_with_upwards_trend:",
                MessageType.RUN_SUMMARY: ":clipboard:",
            }
            emoji = emoji_map.get(message.message_type, ":information_source:")
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{emoji} {title}"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": body},
                },
            ]
            # Add fields if present in payload
            fields = payload.get("fields")
            if fields and isinstance(fields, dict):
                field_elements = [
                    {"type": "mrkdwn", "text": f"*{k}*\n{v}"}
                    for k, v in fields.items()
                ]
                blocks.append({"type": "section", "fields": field_elements[:10]})
            return blocks

        if message.message_type == MessageType.SYSTEM:
            return [
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f":gear: _{message.content or 'System message'}_"}
                    ],
                }
            ]

        return None

    # ------------------------------------------------------------------
    # Inbound relay: Slack → Amprealize
    # ------------------------------------------------------------------

    async def handle_event(self, event_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dispatch a Slack event to the appropriate handler.

        Called after signature verification.
        Returns a response dict (or None for no response).
        """
        event_type = event_payload.get("type")

        # URL verification challenge
        if event_type == "url_verification":
            return {"challenge": event_payload.get("challenge", "")}

        # Events API wrapper
        if event_type == "event_callback":
            event = event_payload.get("event", {})
            inner_type = event.get("type")

            if inner_type == "message":
                await self._handle_slack_message(event, event_payload)
            elif inner_type == "reaction_added":
                await self._handle_slack_reaction_added(event)
            elif inner_type == "reaction_removed":
                await self._handle_slack_reaction_removed(event)

        return None

    async def _handle_slack_message(
        self, event: Dict[str, Any], envelope: Dict[str, Any]
    ) -> None:
        """Handle an inbound message from Slack."""
        # Ignore bot messages (including our own)
        if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            return

        slack_ts = event.get("ts", "")
        if self._is_echo(slack_ts):
            return

        channel_id = event.get("channel", "")
        slack_user = event.get("user", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")

        if not channel_id or not slack_user or not text:
            return

        # Look up the binding for this channel
        binding = self._conversation.get_external_binding(
            provider=ExternalProvider.SLACK,
            external_channel_id=channel_id,
        )
        if binding is None:
            return

        # Determine parent_id for threaded replies
        parent_id = None
        if thread_ts and thread_ts != slack_ts:
            parent_id = self.get_amprealize_message_id(channel_id, thread_ts)

        # Map Slack user to an Amprealize actor ID
        actor_id = f"slack:{slack_user}"

        # Create the message in Amprealize
        try:
            msg = self._conversation.send_message(
                binding.conversation_id,
                sender_id=actor_id,
                sender_type=ActorType.USER,
                content=text,
                message_type=MessageType.TEXT,
                parent_id=parent_id,
                metadata={"slack_ts": slack_ts, "slack_channel": channel_id, "source": "slack"},
            )
            # Store the mapping for thread correlation
            self.store_thread_mapping(msg.id, channel_id, slack_ts)
        except Exception:
            logger.exception("Failed to relay Slack message to Amprealize (channel=%s)", channel_id)

    async def _handle_slack_reaction_added(self, event: Dict[str, Any]) -> None:
        """Handle a reaction_added event from Slack."""
        channel_id = event.get("item", {}).get("channel", "")
        message_ts = event.get("item", {}).get("ts", "")
        emoji = event.get("reaction", "")
        slack_user = event.get("user", "")

        if not all([channel_id, message_ts, emoji, slack_user]):
            return

        message_id = self.get_amprealize_message_id(channel_id, message_ts)
        if message_id is None:
            return

        actor_id = f"slack:{slack_user}"
        try:
            self._conversation.add_reaction(
                message_id,
                actor_id=actor_id,
                actor_type=ActorType.USER,
                emoji=f":{emoji}:",
            )
        except Exception:
            logger.debug("Failed to sync Slack reaction to Amprealize", exc_info=True)

    async def _handle_slack_reaction_removed(self, event: Dict[str, Any]) -> None:
        """Handle a reaction_removed event from Slack."""
        channel_id = event.get("item", {}).get("channel", "")
        message_ts = event.get("item", {}).get("ts", "")
        emoji = event.get("reaction", "")
        slack_user = event.get("user", "")

        if not all([channel_id, message_ts, emoji, slack_user]):
            return

        message_id = self.get_amprealize_message_id(channel_id, message_ts)
        if message_id is None:
            return

        actor_id = f"slack:{slack_user}"
        try:
            self._conversation.remove_reaction(
                message_id,
                actor_id=actor_id,
                emoji=f":{emoji}:",
            )
        except Exception:
            logger.debug("Failed to sync Slack reaction removal to Amprealize", exc_info=True)

    # ------------------------------------------------------------------
    # Slash command: /amprealize connect
    # ------------------------------------------------------------------

    async def handle_slash_command(
        self, command_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle a /amprealize slash command from Slack.

        Supported subcommands:
            /amprealize connect <project_id>   — bind this channel to a project room
            /amprealize disconnect             — remove the binding
            /amprealize status                 — show binding status

        Returns a Slack response message dict.
        """
        text = (command_payload.get("text") or "").strip()
        channel_id = command_payload.get("channel_id", "")
        team_id = command_payload.get("team_id", "")
        user_id = command_payload.get("user_id", "")

        parts = text.split(None, 1)
        subcommand = parts[0].lower() if parts else ""

        if subcommand == "connect":
            return await self._cmd_connect(parts, channel_id, team_id, user_id)
        elif subcommand == "disconnect":
            return await self._cmd_disconnect(channel_id, user_id)
        elif subcommand == "status":
            return await self._cmd_status(channel_id)
        else:
            return {
                "response_type": "ephemeral",
                "text": (
                    "Usage:\n"
                    "  `/amprealize connect <project_id>` — Bind this channel to an Amprealize project\n"
                    "  `/amprealize disconnect` — Remove the binding\n"
                    "  `/amprealize status` — Show current binding"
                ),
            }

    async def _cmd_connect(
        self,
        parts: List[str],
        channel_id: str,
        team_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Handle /amprealize connect <project_id>."""
        if len(parts) < 2:
            return {
                "response_type": "ephemeral",
                "text": "Usage: `/amprealize connect <project_id>`",
            }

        project_id = parts[1].strip()
        actor_id = f"slack:{user_id}"

        # Check if a binding already exists
        existing = self._conversation.get_external_binding(
            provider=ExternalProvider.SLACK,
            external_channel_id=channel_id,
        )
        if existing and existing.is_active:
            return {
                "response_type": "ephemeral",
                "text": f":warning: This channel is already connected to conversation `{existing.conversation_id}`.\nUse `/amprealize disconnect` first.",
            }

        try:
            # Get or create the project room conversation
            conversation = self._conversation.create_conversation(
                project_id=project_id,
                scope=ConversationScope.PROJECT_ROOM,
                title=f"Slack Bridge - #{channel_id}",
                created_by=actor_id,
            )

            # Create the external binding
            self._conversation.create_external_binding(
                conversation_id=conversation.id,
                provider=ExternalProvider.SLACK,
                external_channel_id=channel_id,
                external_workspace_id=team_id,
                config={"connected_via": "slash_command"},
                bound_by=actor_id,
            )

            return {
                "response_type": "in_channel",
                "text": f":white_check_mark: Connected! This channel is now bridged to Amprealize project `{project_id}`.\nMessages here will appear in Amprealize, and vice versa.",
            }
        except Exception as e:
            logger.exception("Failed to connect Slack channel %s", channel_id)
            return {
                "response_type": "ephemeral",
                "text": f":x: Failed to connect: {e}",
            }

    async def _cmd_disconnect(self, channel_id: str, user_id: str) -> Dict[str, Any]:
        """Handle /amprealize disconnect."""
        binding = self._conversation.get_external_binding(
            provider=ExternalProvider.SLACK,
            external_channel_id=channel_id,
        )
        if binding is None:
            return {
                "response_type": "ephemeral",
                "text": ":information_source: This channel is not connected to Amprealize.",
            }

        try:
            self._conversation.deactivate_external_binding(binding.id)
            return {
                "response_type": "in_channel",
                "text": ":wave: Disconnected. This channel is no longer bridged to Amprealize.",
            }
        except Exception as e:
            logger.exception("Failed to disconnect channel %s", channel_id)
            return {
                "response_type": "ephemeral",
                "text": f":x: Failed to disconnect: {e}",
            }

    async def _cmd_status(self, channel_id: str) -> Dict[str, Any]:
        """Handle /amprealize status."""
        binding = self._conversation.get_external_binding(
            provider=ExternalProvider.SLACK,
            external_channel_id=channel_id,
        )
        if binding is None:
            return {
                "response_type": "ephemeral",
                "text": ":information_source: This channel is not connected to Amprealize.",
            }
        return {
            "response_type": "ephemeral",
            "text": (
                f":link: *Connected to Amprealize*\n"
                f"• Conversation: `{binding.conversation_id}`\n"
                f"• Provider: `{binding.provider.value}`\n"
                f"• Bound by: `{binding.bound_by}`\n"
                f"• Bound at: {binding.bound_at.isoformat() if binding.bound_at else 'unknown'}"
            ),
        }

    # ------------------------------------------------------------------
    # Event hub subscription (outbound relay trigger)
    # ------------------------------------------------------------------

    async def on_amprealize_event(
        self,
        event_type: str,
        conversation_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Handle an Amprealize event for outbound relay.

        Called by the event hub subscriber to relay events to Slack.
        """
        binding = self._conversation.get_binding_by_conversation(
            conversation_id, ExternalProvider.SLACK
        )
        if binding is None:
            return

        # Don't relay messages that came from Slack (avoid loops)
        metadata = payload.get("metadata", {})
        if metadata.get("source") == "slack":
            return

        if event_type == EVENT_MESSAGE_NEW:
            await self._relay_new_message(payload, binding)
        elif event_type == EVENT_REACTION_ADDED:
            await self._relay_reaction_added(payload, binding)
        elif event_type == EVENT_REACTION_REMOVED:
            await self._relay_reaction_removed(payload, binding)

    async def _relay_new_message(
        self, payload: Dict[str, Any], binding: ExternalBinding
    ) -> None:
        """Relay a new Amprealize message to Slack."""
        message_id = payload.get("message_id") or payload.get("id")
        if not message_id:
            return

        # Build a lightweight Message-like for relay
        content = payload.get("content", "")
        sender_type_str = payload.get("sender_type", "user")
        msg_type_str = payload.get("message_type", "text")
        parent_id = payload.get("parent_id")

        try:
            sender_type = ActorType(sender_type_str)
        except ValueError:
            sender_type = ActorType.USER

        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            msg_type = MessageType.TEXT

        msg = Message(
            id=message_id,
            conversation_id=payload.get("conversation_id", ""),
            sender_id=payload.get("sender_id", ""),
            sender_type=sender_type,
            content=content,
            message_type=msg_type,
            structured_payload=payload.get("structured_payload"),
            parent_id=parent_id,
            metadata=payload.get("metadata", {}),
        )

        await self.relay_to_slack(msg, binding)

    async def _relay_reaction_added(
        self, payload: Dict[str, Any], binding: ExternalBinding
    ) -> None:
        """Relay an Amprealize reaction to Slack."""
        message_id = payload.get("message_id")
        emoji = payload.get("emoji", "")
        if not message_id or not emoji:
            return

        slack_ts = self.get_slack_ts(message_id)
        if slack_ts is None:
            return

        await self.add_slack_reaction(binding.external_channel_id, slack_ts, emoji)

    async def _relay_reaction_removed(
        self, payload: Dict[str, Any], binding: ExternalBinding
    ) -> None:
        """Relay an Amprealize reaction removal to Slack."""
        message_id = payload.get("message_id")
        emoji = payload.get("emoji", "")
        if not message_id or not emoji:
            return

        slack_ts = self.get_slack_ts(message_id)
        if slack_ts is None:
            return

        await self.remove_slack_reaction(binding.external_channel_id, slack_ts, emoji)
