#!/usr/bin/env bash
# Setup GitHub OAuth credentials for Amprealize device flow
# Follows: behavior_externalize_configuration, behavior_prevent_secret_leaks

set -euo pipefail

# Color output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check for required tools
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is required but not installed${NC}"
    echo "Install with: brew install jq"
    exit 1
fi

echo -e "${GREEN}=== Amprealize GitHub OAuth Setup ===${NC}"
echo ""

# Check if .env already has OAuth config
ENV_FILE="${AMPREALIZE_ROOT:-.}/.env"
if [[ -f "$ENV_FILE" ]] && grep -q "OAUTH_CLIENT_ID" "$ENV_FILE"; then
    echo -e "${YELLOW}Warning: .env already contains OAUTH_CLIENT_ID${NC}"
    echo "Do you want to overwrite it? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo "This script will help you:"
echo "  1. Check for existing GitHub OAuth Apps"
echo "  2. Create a new OAuth App (if needed)"
echo "  3. Configure Amprealize with OAuth credentials"
echo ""

# Check for GitHub CLI or prompt for token
if command -v gh &> /dev/null; then
    echo -e "${GREEN}✓ GitHub CLI (gh) detected${NC}"
    if gh auth status &> /dev/null; then
        echo -e "${GREEN}✓ GitHub CLI authenticated${NC}"
        USE_GH_CLI=true
    else
        echo -e "${YELLOW}⚠ GitHub CLI not authenticated${NC}"
        echo "Run: gh auth login"
        USE_GH_CLI=false
    fi
else
    echo -e "${YELLOW}GitHub CLI (gh) not found${NC}"
    echo "Install it from: https://cli.github.com/"
    USE_GH_CLI=false
fi

echo ""
echo "Choose an option:"
echo "  1) List existing OAuth Apps (requires GitHub token)"
echo "  2) Create new OAuth App (requires GitHub token)"
echo "  3) Enter existing credentials manually"
echo ""
read -p "Enter choice (1-3): " choice

case $choice in
    1|2)
        # Need GitHub authentication
        if [[ "$USE_GH_CLI" == "true" ]]; then
            echo -e "${GREEN}Using GitHub CLI authentication${NC}"
            GH_TOKEN=$(gh auth token)
        else
            echo ""
            echo -e "${BLUE}GitHub Personal Access Token needed${NC}"
            echo "Create one at: https://github.com/settings/tokens/new"
            echo "Required scopes: write:org (for OAuth Apps)"
            echo ""
            read -p "Enter GitHub token: " -s GH_TOKEN
            echo ""

            if [[ -z "$GH_TOKEN" ]]; then
                echo -e "${RED}Error: Token required${NC}"
                exit 1
            fi
        fi

        # Get username
        USER_INFO=$(curl -s -H "Authorization: token $GH_TOKEN" https://api.github.com/user)
        GH_USERNAME=$(echo "$USER_INFO" | grep -o '"login": *"[^"]*"' | cut -d'"' -f4)

        if [[ -z "$GH_USERNAME" ]]; then
            echo -e "${RED}Error: Failed to authenticate with GitHub${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ Authenticated as: $GH_USERNAME${NC}"
        echo ""

        if [[ "$choice" == "1" ]]; then
            # List existing OAuth Apps
            echo -e "${BLUE}Fetching your OAuth Apps...${NC}"
            echo ""

            APPS=$(curl -s -H "Authorization: token $GH_TOKEN" \
                "https://api.github.com/user/applications")

            # Parse and display apps
            APP_COUNT=$(echo "$APPS" | grep -c '"name":' || true)

            if [[ "$APP_COUNT" -eq 0 ]]; then
                echo -e "${YELLOW}No existing OAuth Apps found${NC}"
                echo ""
                read -p "Create a new OAuth App? (y/N): " create_new
                if [[ "$create_new" =~ ^[Yy]$ ]]; then
                    choice=2
                else
                    echo "Cancelled."
                    exit 0
                fi
            else
                echo -e "${GREEN}Found $APP_COUNT OAuth App(s):${NC}"
                echo ""

                # Display apps with numbering
                i=1
                while IFS= read -r line; do
                    if [[ "$line" =~ \"name\":[[:space:]]*\"([^\"]+)\" ]]; then
                        APP_NAME="${BASH_REMATCH[1]}"
                        echo "  $i) $APP_NAME"
                        ((i++))
                    fi
                done <<< "$APPS"

                echo ""
                read -p "Select an app (1-$APP_COUNT) or create new (n): " selection

                if [[ "$selection" =~ ^[Nn]$ ]]; then
                    choice=2
                elif [[ "$selection" =~ ^[0-9]+$ ]] && [[ "$selection" -ge 1 ]] && [[ "$selection" -le "$APP_COUNT" ]]; then
                    # Get selected app details
                    SELECTED_APP=$(echo "$APPS" | jq ".[$((selection-1))]")
                    APP_NAME=$(echo "$SELECTED_APP" | jq -r '.name')
                    CLIENT_ID=$(echo "$SELECTED_APP" | jq -r '.client_id')

                    echo ""
                    echo -e "${GREEN}Selected: $APP_NAME${NC}"
                    echo -e "${GREEN}Client ID: $CLIENT_ID${NC}"
                    echo ""
                    echo -e "${YELLOW}⚠ You'll need to manually get the Client Secret from:${NC}"
                    echo "  https://github.com/settings/developers"
                    echo ""

                    choice=3  # Continue with manual entry
                else
                    echo -e "${RED}Invalid selection${NC}"
                    exit 1
                fi
            fi
        fi

        if [[ "$choice" == "2" ]]; then
            # Create new OAuth App
            echo -e "${BLUE}Creating new OAuth App...${NC}"
            echo ""

            read -p "App name [Amprealize Device Flow]: " APP_NAME
            APP_NAME=${APP_NAME:-"Amprealize Device Flow"}

            read -p "Homepage URL [https://github.com/$GH_USERNAME/amprealize]: " HOMEPAGE_URL
            HOMEPAGE_URL=${HOMEPAGE_URL:-"https://github.com/$GH_USERNAME/amprealize"}

            read -p "Callback URL [http://localhost:8000/auth/callback]: " CALLBACK_URL
            CALLBACK_URL=${CALLBACK_URL:-"http://localhost:8000/auth/callback"}

            echo ""
            echo "Creating OAuth App with:"
            echo "  Name: $APP_NAME"
            echo "  Homepage: $HOMEPAGE_URL"
            echo "  Callback: $CALLBACK_URL"
            echo ""

            # Create the app
            CREATE_RESULT=$(curl -s -X POST \
                -H "Authorization: token $GH_TOKEN" \
                -H "Accept: application/vnd.github.v3+json" \
                https://api.github.com/user/applications \
                -d "{
                    \"name\": \"$APP_NAME\",
                    \"url\": \"$HOMEPAGE_URL\",
                    \"callback_url\": \"$CALLBACK_URL\"
                }")

            CLIENT_ID=$(echo "$CREATE_RESULT" | jq -r '.client_id')
            CLIENT_SECRET=$(echo "$CREATE_RESULT" | jq -r '.client_secret')

            if [[ "$CLIENT_ID" == "null" ]] || [[ -z "$CLIENT_ID" ]]; then
                echo -e "${RED}Error: Failed to create OAuth App${NC}"
                echo "$CREATE_RESULT" | jq .
                exit 1
            fi

            echo -e "${GREEN}✓ OAuth App created successfully!${NC}"
            echo ""
            echo -e "${GREEN}Client ID: $CLIENT_ID${NC}"
            echo -e "${GREEN}Client Secret: ${CLIENT_SECRET:0:10}...${NC}"
            echo ""
            echo -e "${YELLOW}⚠ IMPORTANT: Save the Client Secret now!${NC}"
            echo "  You won't be able to see it again."
            echo ""
            echo "Manage your app at: https://github.com/settings/developers"
            echo ""

            read -p "Continue with configuration? (Y/n): " continue_config
            if [[ "$continue_config" =~ ^[Nn]$ ]]; then
                echo "OAuth App created but not configured."
                echo "Run this script again to configure."
                exit 0
            fi

            # Skip to configuration
            choice=3
        fi
        ;;
    3)
        echo -e "${BLUE}Manual credential entry${NC}"
        echo ""
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

# Manual credential entry (or continuation from API flow)
if [[ "$choice" == "3" ]] && [[ -z "${CLIENT_ID:-}" ]]; then
    # Prompt for Client ID
# Manual credential entry (or continuation from API flow)
if [[ "$choice" == "3" ]] && [[ -z "${CLIENT_ID:-}" ]]; then
    # Prompt for Client ID
    echo -e "${GREEN}Enter your GitHub OAuth Client ID:${NC}"
    echo "(Should start with Iv1. or Iv23)"
    read -r CLIENT_ID
fi

if [[ ! "$CLIENT_ID" =~ ^Iv[0-9]+\. ]]; then
    echo -e "${RED}Error: Client ID should start with 'Iv1.' or 'Iv23'${NC}"
    echo "Please check your GitHub OAuth app settings."
    exit 1
fi

# Prompt for Client Secret if not already set
if [[ -z "${CLIENT_SECRET:-}" ]]; then
    echo ""
    echo -e "${GREEN}Enter your GitHub OAuth Client Secret:${NC}"
    echo "(This will not be displayed)"
    read -rs CLIENT_SECRET
fi

if [[ -z "$CLIENT_SECRET" ]]; then
    echo -e "${RED}Error: Client Secret cannot be empty${NC}"
    exit 1
fi

# Verify secret length (typical GitHub secrets are 40 characters)
SECRET_LEN=${#CLIENT_SECRET}
if [[ $SECRET_LEN -lt 20 ]]; then
    echo -e "${YELLOW}Warning: Client Secret seems short ($SECRET_LEN chars)${NC}"
    echo "Are you sure this is correct? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo ""
echo -e "${GREEN}Configuring OAuth credentials...${NC}"

# Create or update .env file
OAUTH_ENV_FILE="${AMPREALIZE_ROOT:-.}/.env.github-oauth"

cat > "$OAUTH_ENV_FILE" <<EOF
# GitHub OAuth Configuration
# Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# DO NOT COMMIT THIS FILE

OAUTH_CLIENT_ID=$CLIENT_ID
OAUTH_CLIENT_SECRET=$CLIENT_SECRET

# GitHub OAuth URLs (defaults)
OAUTH_DEVICE_CODE_URL=https://github.com/login/device/code
OAUTH_TOKEN_URL=https://github.com/login/oauth/access_token
OAUTH_USER_URL=https://api.github.com/user

# Device Flow Settings (optional overrides)
# AMPREALIZE_DEVICE_VERIFICATION_URI=https://device.amprealize.dev/activate
# AMPREALIZE_DEVICE_CODE_TTL_SECONDS=600
# AMPREALIZE_DEVICE_POLL_INTERVAL_SECONDS=5
# AMPREALIZE_ACCESS_TOKEN_TTL_SECONDS=3600
# AMPREALIZE_REFRESH_TOKEN_TTL_SECONDS=604800
EOF

chmod 600 "$OAUTH_ENV_FILE"

echo -e "${GREEN}✓ OAuth credentials saved to $OAUTH_ENV_FILE${NC}"
echo ""

# Ensure .gitignore excludes this file
GITIGNORE_FILE="${AMPREALIZE_ROOT:-.}/.gitignore"
if [[ -f "$GITIGNORE_FILE" ]]; then
    if ! grep -q ".env.github-oauth" "$GITIGNORE_FILE"; then
        echo ".env.github-oauth" >> "$GITIGNORE_FILE"
        echo -e "${GREEN}✓ Added .env.github-oauth to .gitignore${NC}"
    fi
else
    echo ".env.github-oauth" > "$GITIGNORE_FILE"
    echo -e "${GREEN}✓ Created .gitignore with .env.github-oauth${NC}"
fi

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "To use these credentials:"
echo ""
echo "  1. Load them in your shell:"
echo "     $ source $OAUTH_ENV_FILE"
echo ""
echo "  2. Or use with API server:"
echo "     $ source $OAUTH_ENV_FILE"
echo "     $ uvicorn amprealize.api:app --host 127.0.0.1 --port 8000"
echo ""
echo "  3. Or with integration tests:"
echo "     $ source $OAUTH_ENV_FILE"
echo "     $ ./scripts/run_tests.sh tests/integration/test_staging_device_flow.py"
echo ""
echo "Verify configuration:"
echo "  $ python scripts/verify_oauth_config.py"
echo ""
