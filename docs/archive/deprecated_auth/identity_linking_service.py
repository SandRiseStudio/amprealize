"""
Identity Linking Service for OAuth-to-Internal-User mapping.

This service handles the linking of external OAuth identities (GitHub, Google)
to internal Amprealize user accounts, supporting:
- Automatic linking for new users (creates account)
- Automatic linking when OAuth email matches existing user
- Manual linking with password confirmation (prevents account takeover)
- Multiple OAuth identities per user

Security features:
- Password confirmation required when linking to existing account with different email
- Email verification check before automatic linking
- Audit trail for all linking operations
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple
from enum import Enum

from .models import User, FederatedIdentity
from .user_service_postgres import PostgresUserService
from .providers.base import UserInfo

logger = logging.getLogger(__name__)


def _dict_to_federated_identity(data: dict) -> FederatedIdentity:
    """Convert a dict from database to FederatedIdentity dataclass."""
    return FederatedIdentity(
        id=data.get("id"),
        user_id=data.get("user_id"),
        provider=data.get("provider"),
        provider_user_id=data.get("provider_user_id"),
        provider_email=data.get("provider_email"),
        provider_username=data.get("provider_username"),
        provider_display_name=data.get("provider_display_name"),
        provider_avatar_url=data.get("provider_avatar_url"),
        access_token_encrypted=data.get("access_token_encrypted"),
        refresh_token_encrypted=data.get("refresh_token_encrypted"),
        token_expires_at=data.get("token_expires_at"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


class LinkingResult(str, Enum):
    """Result of identity linking attempt."""
    LINKED_NEW_USER = "linked_new_user"  # Created new user and linked
    LINKED_EXISTING = "linked_existing"  # Linked to existing user (auto)
    LINKED_MANUAL = "linked_manual"  # Linked via manual confirmation
    ALREADY_LINKED = "already_linked"  # Identity already linked to this user
    REQUIRES_PASSWORD = "requires_password"  # Need password to confirm link
    REQUIRES_MFA = "requires_mfa"  # Need MFA verification to confirm link
    EMAIL_CONFLICT = "email_conflict"  # Email belongs to different user
    INVALID_PASSWORD = "invalid_password"  # Password confirmation failed
    ERROR = "error"  # General error


@dataclass
class LinkingResponse:
    """Response from identity linking attempt."""
    result: LinkingResult
    user: Optional[User] = None
    federated_identity: Optional[FederatedIdentity] = None
    message: Optional[str] = None
    requires_email: Optional[str] = None  # Email to confirm for manual linking


class IdentityLinkingService:
    """
    Service for linking OAuth identities to internal users.

    Implements the following linking strategies:
    1. If OAuth identity already linked → return existing user
    2. If OAuth email matches existing user email → auto-link (if email verified)
    3. If user provides password → manual link with confirmation
    4. Otherwise → create new user and link
    """

    def __init__(
        self,
        user_service: PostgresUserService,
        require_email_verification: bool = True,
    ):
        """
        Initialize identity linking service.

        Args:
            user_service: PostgreSQL user service for database operations
            require_email_verification: Whether to require email verification for auto-linking
        """
        self._user_service = user_service
        self._require_email_verification = require_email_verification

    def link_identity(
        self,
        oauth_user_info: UserInfo,
        oauth_access_token: str,
        oauth_refresh_token: Optional[str] = None,
        password_confirmation: Optional[str] = None,
        target_user_id: Optional[str] = None,
    ) -> LinkingResponse:
        """
        Link an OAuth identity to an internal user.

        Args:
            oauth_user_info: User info from OAuth provider
            oauth_access_token: OAuth access token (encrypted for storage)
            oauth_refresh_token: Optional OAuth refresh token
            password_confirmation: Password to confirm linking to existing account
            target_user_id: Specific user ID to link to (for manual linking)

        Returns:
            LinkingResponse with result and user/identity info
        """
        try:
            # 1. Check if this OAuth identity is already linked
            existing_identity_data = self._user_service.get_federated_identity_by_provider(
                provider=oauth_user_info.provider,
                provider_user_id=oauth_user_info.user_id,
            )

            if existing_identity_data:
                # Already linked - fetch and return the user
                existing_identity = _dict_to_federated_identity(existing_identity_data)
                user = self._user_service.get_user_by_id(existing_identity.user_id)
                if user:
                    # Update tokens
                    self._user_service.update_federated_identity_tokens(
                        identity_id=existing_identity.id,
                        access_token=oauth_access_token,
                        refresh_token=oauth_refresh_token,
                    )
                    logger.info(f"OAuth identity already linked: {oauth_user_info.provider}:{oauth_user_info.user_id} → user {user.id}")
                    return LinkingResponse(
                        result=LinkingResult.ALREADY_LINKED,
                        user=user,
                        federated_identity=existing_identity,
                        message="Identity already linked to your account",
                    )

            # 2. Check if we have an email from OAuth
            oauth_email = oauth_user_info.email

            # 3. If manual linking with target user and password
            if target_user_id and password_confirmation:
                return self._link_with_password_confirmation(
                    oauth_user_info=oauth_user_info,
                    oauth_access_token=oauth_access_token,
                    oauth_refresh_token=oauth_refresh_token,
                    target_user_id=target_user_id,
                    password=password_confirmation,
                )

            # 4. Check if OAuth email matches an existing user
            if oauth_email:
                existing_user = self._user_service.get_user_by_email(oauth_email)

                if existing_user:
                    # Email matches - check if we can auto-link
                    if self._require_email_verification and not existing_user.email_verified:
                        # User exists but email not verified - require password
                        logger.info(f"Email match but not verified: {oauth_email}")
                        return LinkingResponse(
                            result=LinkingResult.REQUIRES_PASSWORD,
                            message="Please confirm your password to link this account",
                            requires_email=oauth_email,
                        )

                    # Auto-link: email matches verified user
                    identity = self._create_federated_identity(
                        user_id=existing_user.id,
                        oauth_user_info=oauth_user_info,
                        oauth_access_token=oauth_access_token,
                        oauth_refresh_token=oauth_refresh_token,
                    )

                    logger.info(f"Auto-linked OAuth identity: {oauth_user_info.provider}:{oauth_user_info.user_id} → user {existing_user.id} (email match)")
                    return LinkingResponse(
                        result=LinkingResult.LINKED_EXISTING,
                        user=existing_user,
                        federated_identity=identity,
                        message="Account linked successfully via email match",
                    )

            # 5. No existing link or email match - create new user
            return self._create_new_user_and_link(
                oauth_user_info=oauth_user_info,
                oauth_access_token=oauth_access_token,
                oauth_refresh_token=oauth_refresh_token,
            )

        except Exception as e:
            logger.exception(f"Error linking identity: {e}")
            return LinkingResponse(
                result=LinkingResult.ERROR,
                message=f"Failed to link identity: {str(e)}",
            )

    def _link_with_password_confirmation(
        self,
        oauth_user_info: UserInfo,
        oauth_access_token: str,
        oauth_refresh_token: Optional[str],
        target_user_id: str,
        password: str,
    ) -> LinkingResponse:
        """Link OAuth identity to existing user with password confirmation."""

        # Get the target user
        user = self._user_service.get_user_by_id(target_user_id)
        if not user:
            return LinkingResponse(
                result=LinkingResult.ERROR,
                message="User not found",
            )

        # Verify password
        if not user.hashed_password or not self._user_service._verify_password(password, user.hashed_password):
            logger.warning(f"Password verification failed for user {target_user_id}")
            return LinkingResponse(
                result=LinkingResult.INVALID_PASSWORD,
                message="Invalid password",
            )

        # Check if this provider is already linked to the user
        existing_identities_data = self._user_service.get_user_federated_identities(target_user_id)
        for identity_data in existing_identities_data:
            if identity_data["provider"] == oauth_user_info.provider and identity_data["provider_user_id"] == oauth_user_info.user_id:
                # Already linked
                identity = _dict_to_federated_identity(identity_data)
                self._user_service.update_federated_identity_tokens(
                    identity_id=identity.id,
                    access_token=oauth_access_token,
                    refresh_token=oauth_refresh_token,
                )
                return LinkingResponse(
                    result=LinkingResult.ALREADY_LINKED,
                    user=user,
                    federated_identity=identity,
                    message="Identity already linked to your account",
                )

        # Create new federated identity
        identity = self._create_federated_identity(
            user_id=target_user_id,
            oauth_user_info=oauth_user_info,
            oauth_access_token=oauth_access_token,
            oauth_refresh_token=oauth_refresh_token,
        )

        logger.info(f"Manually linked OAuth identity: {oauth_user_info.provider}:{oauth_user_info.user_id} → user {target_user_id}")
        return LinkingResponse(
            result=LinkingResult.LINKED_MANUAL,
            user=user,
            federated_identity=identity,
            message="Account linked successfully",
        )

    def _create_new_user_and_link(
        self,
        oauth_user_info: UserInfo,
        oauth_access_token: str,
        oauth_refresh_token: Optional[str],
    ) -> LinkingResponse:
        """Create a new user from OAuth info and link the identity."""

        # Generate username from OAuth info
        if oauth_user_info.username:
            username = oauth_user_info.username
        elif oauth_user_info.email:
            username = oauth_user_info.email.split("@")[0]
        else:
            username = f"{oauth_user_info.provider}_{oauth_user_info.user_id}"

        # Ensure username is unique
        base_username = username
        suffix = 0
        while self._user_service.get_user_by_username(username):
            suffix += 1
            username = f"{base_username}_{suffix}"

        # Create new user (no password since they're using OAuth)
        user = self._user_service.create_user(
            username=username,
            email=oauth_user_info.email,
            password=None,  # OAuth-only user
            display_name=oauth_user_info.display_name,
        )

        # If OAuth provided email, mark as verified (OAuth provider verified it)
        if oauth_user_info.email and user:
            self._user_service.mark_email_verified(user.id)

        # Create federated identity
        identity = self._create_federated_identity(
            user_id=user.id,
            oauth_user_info=oauth_user_info,
            oauth_access_token=oauth_access_token,
            oauth_refresh_token=oauth_refresh_token,
        )

        logger.info(f"Created new user and linked OAuth: {oauth_user_info.provider}:{oauth_user_info.user_id} → new user {user.id}")
        return LinkingResponse(
            result=LinkingResult.LINKED_NEW_USER,
            user=user,
            federated_identity=identity,
            message="Account created and linked successfully",
        )

    def _create_federated_identity(
        self,
        user_id: str,
        oauth_user_info: UserInfo,
        oauth_access_token: str,
        oauth_refresh_token: Optional[str],
    ) -> FederatedIdentity:
        """Create a federated identity record."""
        identity_id = self._user_service.create_federated_identity(
            user_id=user_id,
            provider=oauth_user_info.provider,
            provider_user_id=oauth_user_info.user_id,
            provider_email=oauth_user_info.email,
            provider_username=oauth_user_info.username,
            provider_display_name=oauth_user_info.display_name,
            provider_avatar_url=oauth_user_info.avatar_url,
            access_token_encrypted=oauth_access_token,
            refresh_token_encrypted=oauth_refresh_token,
        )

        # Return the created identity - convert dict to dataclass
        identity_data = self._user_service.get_federated_identity_by_provider(
            provider=oauth_user_info.provider,
            provider_user_id=oauth_user_info.user_id,
        )
        return _dict_to_federated_identity(identity_data)

    def unlink_identity(
        self,
        user_id: str,
        provider: str,
        password_confirmation: str,
    ) -> Tuple[bool, str]:
        """
        Unlink an OAuth identity from a user.

        Args:
            user_id: User ID to unlink from
            provider: OAuth provider to unlink (github, google)
            password_confirmation: Password to confirm unlinking

        Returns:
            Tuple of (success, message)
        """
        # Get the user first
        user = self._user_service.get_user_by_id(user_id)
        if not user:
            return False, "User not found"

        # Verify password
        if not user.hashed_password or not self._user_service._verify_password(password_confirmation, user.hashed_password):
            return False, "Invalid password"

        # Check that user has other auth methods before unlinking
        identities_data = self._user_service.get_user_federated_identities(user_id)
        has_password = user.hashed_password is not None
        other_identities = [i for i in identities_data if i["provider"] != provider]

        if not has_password and not other_identities:
            return False, "Cannot unlink last authentication method. Set a password first."

        # Find and delete the identity
        for identity_data in identities_data:
            if identity_data["provider"] == provider:
                self._user_service.delete_federated_identity(identity_data["id"])
                logger.info(f"Unlinked OAuth identity: {provider} from user {user_id}")
                return True, f"{provider.title()} account unlinked successfully"

        return False, f"No {provider} account linked"

    def get_user_identities(self, user_id: str) -> list[FederatedIdentity]:
        """Get all OAuth identities linked to a user."""
        identities_data = self._user_service.get_user_federated_identities(user_id)
        return [_dict_to_federated_identity(data) for data in identities_data]
