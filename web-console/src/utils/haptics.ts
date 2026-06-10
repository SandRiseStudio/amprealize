/**
 * Web Vibration API — light tactile feedback for chat actions.
 * No-op when unsupported or reduced-motion preference (callers may still gate).
 */

const receiveHapticSeen = new Set<string>();
const receiveHapticOrder: string[] = [];
const RECEIVE_HAPTIC_CAP = 200;

function rememberReceiveHaptic(messageId: string): boolean {
  if (receiveHapticSeen.has(messageId)) return false;
  receiveHapticSeen.add(messageId);
  receiveHapticOrder.push(messageId);
  while (receiveHapticOrder.length > RECEIVE_HAPTIC_CAP) {
    const old = receiveHapticOrder.shift();
    if (old) receiveHapticSeen.delete(old);
  }
  return true;
}

export function haptic(pattern: number | number[] = 8): void {
  if (typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function') return;
  try {
    navigator.vibrate(pattern);
  } catch {
    /* ignore */
  }
}

/** Short pulse for send / selection */
export function hapticSend(): void {
  haptic(10);
}

/** Double-tap feel for reactions */
export function hapticReaction(): void {
  haptic([5, 20, 5]);
}

/** New conversation created */
export function hapticNewConversation(): void {
  haptic(15);
}

/**
 * One-time subtle pulse per message id (avoids repeat on virtualizer remount).
 */
export function hapticReceiveMessageOnce(messageId: string): void {
  if (!rememberReceiveHaptic(messageId)) return;
  haptic(3);
}
