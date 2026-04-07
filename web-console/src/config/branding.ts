/**
 * Amprealize web console — product copy and OAuth surface identifiers.
 * (Rebrand from Amprealize; AMPREALIZE-667 / AMPREALIZE-675.)
 */

/** User-visible product name in the web UI (sentence case: only leading “A” capitalized). */
export const PRODUCT_DISPLAY_NAME = 'Amprealize';

/** OAuth postMessage type from the callback popup to the opener */
export const OAUTH_COMPLETE_MESSAGE_TYPE = 'amprealize:oauth-complete';

/** Legacy postMessage type (still accepted in listeners for one release) */
export const OAUTH_COMPLETE_MESSAGE_TYPE_LEGACY = 'amprealize:oauth-complete';

/** Window name for the Google OAuth popup */
export const OAUTH_GOOGLE_POPUP_NAME = 'amprealize_google_oauth';

/**
 * Public OAuth client id for the web console (device + token exchange).
 * Backend device flow accepts arbitrary client_id strings.
 */
export const OAUTH_WEB_CLIENT_ID = 'amprealize-web-console';
