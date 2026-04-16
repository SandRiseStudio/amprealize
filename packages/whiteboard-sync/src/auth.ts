/**
 * Auth — Token validation for WebSocket upgrade requests.
 *
 * Validates bearer tokens by calling the Python FastAPI backend.  Results are
 * cached briefly (5 s TTL) to avoid excessive HTTP round-trips during
 * reconnection storms.
 */

interface AuthResult {
  id: string;
  name: string;
}

interface CacheEntry {
  result: AuthResult;
  expiresAt: number;
}

const CACHE_TTL_MS = 5_000;
const cache = new Map<string, CacheEntry>();

/**
 * Validate a token against the Python whiteboard API.
 *
 * The Python endpoint `GET /api/v1/whiteboard/rooms/{roomId}` returns room
 * details when the caller is authorized.  We extract the user identity from
 * the response or from a separate `/api/v1/auth/me` call.
 *
 * @throws Error if the token is invalid or the room does not exist
 */
export async function validateToken(
  token: string,
  roomId: string,
  pythonApiBase: string,
): Promise<AuthResult> {
  if (!token) {
    throw new Error("Missing auth token");
  }

  const cacheKey = `${token}:${roomId}`;
  const cached = cache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.result;
  }

  // Validate room access — the Python API will return 401/403 if not allowed
  const roomRes = await fetch(`${pythonApiBase}/whiteboard/rooms/${roomId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!roomRes.ok) {
    cache.delete(cacheKey);
    if (roomRes.status === 401 || roomRes.status === 403) {
      throw new Error("Not authorized for this room");
    }
    if (roomRes.status === 404) {
      throw new Error("Room not found");
    }
    throw new Error(`Upstream auth check failed: ${roomRes.status}`);
  }

  // Resolve user identity
  const meRes = await fetch(`${pythonApiBase}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  let result: AuthResult;
  if (meRes.ok) {
    const meData = (await meRes.json()) as {
      user_id?: string;
      name?: string;
      email?: string;
    };
    result = {
      id: meData.user_id ?? "anonymous",
      name: meData.name ?? meData.email ?? "Anonymous",
    };
  } else {
    // Fallback — room access succeeded so we allow, but with anonymous identity
    result = { id: "anonymous", name: "Anonymous" };
  }

  cache.set(cacheKey, { result, expiresAt: Date.now() + CACHE_TTL_MS });
  return result;
}
