import { describe, expect, it } from 'vitest';
import type { ConversationMessage } from '../lib/collab-client';
import {
  isAgentMessage,
  primaryRouteCategoryFromMessage,
  showExecutionConsentFromNewestFirstMessages,
} from '../components/conversations/messageComposerExecutionConsent';

function msg(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: 'm-id',
    conversation_id: 'c1',
    sender_id: 'u1',
    sender_type: 'user',
    message_type: 'text',
    is_edited: false,
    is_deleted: false,
    metadata: {},
    reactions: [],
    reply_count: 0,
    ...overrides,
  };
}

function agentWithRoute(category: string): ConversationMessage {
  return msg({
    id: 'agent-1',
    sender_type: 'agent',
    metadata: {
      chat_route: { candidates: [{ category }] },
    },
  });
}

describe('messageComposerExecutionConsent', () => {
  describe('isAgentMessage', () => {
    it('treats sender_type agent case-insensitively', () => {
      expect(isAgentMessage(msg({ sender_type: 'agent' }))).toBe(true);
      expect(isAgentMessage(msg({ sender_type: 'Agent' }))).toBe(true);
      expect(isAgentMessage(msg({ sender_type: 'user' }))).toBe(false);
    });
  });

  describe('primaryRouteCategoryFromMessage', () => {
    it('returns null when metadata or chat_route is missing', () => {
      expect(primaryRouteCategoryFromMessage(undefined)).toBeNull();
      expect(primaryRouteCategoryFromMessage(msg({ metadata: {} }))).toBeNull();
    });

    it('reads first candidate category from chat_route', () => {
      const m = msg({
        sender_type: 'agent',
        metadata: {
          chat_route: {
            candidates: [{ category: 'execution_start' }, { category: 'other' }],
          },
        },
      });
      expect(primaryRouteCategoryFromMessage(m)).toBe('execution_start');
    });
  });

  describe('showExecutionConsentFromNewestFirstMessages', () => {
    it('returns false for an empty thread', () => {
      expect(showExecutionConsentFromNewestFirstMessages([])).toBe(false);
    });

    it('returns false when the newest agent message has no execution route', () => {
      const rows = [
        agentWithRoute('query_projects'),
        msg({ sender_type: 'user', id: 'u-old' }),
      ];
      expect(showExecutionConsentFromNewestFirstMessages(rows)).toBe(false);
    });

    it('returns true when the newest agent message is execution_start', () => {
      expect(showExecutionConsentFromNewestFirstMessages([agentWithRoute('execution_start')])).toBe(
        true,
      );
    });

    it('returns true when the newest agent message is execution_cancel', () => {
      expect(showExecutionConsentFromNewestFirstMessages([agentWithRoute('execution_cancel')])).toBe(
        true,
      );
    });

    it('uses the most recent agent message when a newer user message exists', () => {
      const rows = [
        msg({ sender_type: 'user', id: 'newest' }),
        agentWithRoute('execution_start'),
      ];
      expect(showExecutionConsentFromNewestFirstMessages(rows)).toBe(true);
    });

    it('ignores older agent execution hints when a newer agent reply is non-execution', () => {
      const rows = [
        agentWithRoute('query_projects'),
        agentWithRoute('execution_start'),
      ];
      expect(showExecutionConsentFromNewestFirstMessages(rows)).toBe(false);
    });
  });
});
