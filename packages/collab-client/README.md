# @amprealize/collab-client

Cross-surface real-time collaboration client for Amprealize. Works identically in:
- **SaaS** (web-console / Vite + React)
- **VS Code webviews**

## Features

- 🔄 **WebSocket client** with automatic reconnection & exponential backoff
- ✅ **Strong consistency** via server-authoritative versioning
- ⚡ **Optimistic updates** with conflict resolution callbacks
- 🎨 **Cursor & presence** broadcasting
- ⚛️ **React hooks** for easy UI binding
- 🌐 **REST API client** for CRUD operations

## Installation

```bash
# From the monorepo root
npm install -w web-console @amprealize/collab-client

# Or link for local development
npm link ./packages/collab-client
```

## Usage

### React Hook (Recommended)

```tsx
import { useCollaboration, EditOperationType } from '@amprealize/collab-client';

function CollaborativeEditor({ documentId }: { documentId: string }) {
  const {
    document,
    isConnected,
    insert,
    delete: deleteOp,
    replace,
    updateCursor,
    cursors,
    presence,
    error,
  } = useCollaboration({
    config: {
      baseUrl: 'http://localhost:8080',
      userId: 'user-123',
      sessionId: crypto.randomUUID(),
      debug: true,
    },
    documentId,
    onContentChange: (content, doc) => {
      console.log('Content updated:', content.slice(0, 50), '... v' + doc.version);
    },
    onConflict: (serverDoc) => {
      // Return rebased content or null to accept server state
      return null;
    },
  });

  if (!isConnected) {
    return <div>Connecting...</div>;
  }

  return (
    <div>
      <textarea
        value={document?.content ?? ''}
        onChange={(e) => {
          // Simple replace-all for demo; real impl would diff
          replace(0, document?.content.length ?? 0, e.target.value);
        }}
        onSelect={(e) => {
          const target = e.target as HTMLTextAreaElement;
          updateCursor(target.selectionStart, target.selectionEnd);
        }}
      />
      {/* Render remote cursors */}
      {Array.from(cursors.entries()).map(([userId, cursor]) => (
        <div key={userId}>User {userId} at position {cursor.position}</div>
      ))}
      {/* Render remote presence */}
      {Array.from(presence.entries()).map(([userId, info]) => (
        <div key={`presence-${userId}`}>
          {info.display_name ?? userId}: {info.status}
        </div>
      ))}
      {error && <div className="error">{error.message}</div>}
    </div>
  );
}
```

### Direct Client Usage

```ts
import { createCollabClient, EditOperationType } from '@amprealize/collab-client';

const client = createCollabClient({
  baseUrl: 'http://localhost:8080',
  userId: 'user-123',
  debug: true,
});

client.on('connected', (document) => {
  console.log('Connected to document:', document.id, 'v' + document.version);
});

client.on('operation', (op, doc) => {
  console.log('Operation applied:', op.operation_type, 'new version:', doc?.version);
});

client.on('conflict', (expected, got, serverDoc) => {
  console.log('Version conflict! Expected:', expected, 'Got:', got);
  // Handle rebase...
});

// Connect to a document
client.connect('doc-abc-123');

// Send edits
client.sendEdit({
  operation_type: EditOperationType.Insert,
  position: 0,
  content: 'Hello, world!',
});
```

### REST API Client

```ts
import { createCollabApi } from '@amprealize/collab-client';

const api = createCollabApi({
  baseUrl: 'http://localhost:8080',
  authToken: 'optional-bearer-token',
});

// Create workspace
const workspace = await api.createWorkspace({
  name: 'My Workspace',
  owner_id: 'user-123',
});

// Create document
const doc = await api.createDocument({
  workspace_id: workspace.id,
  title: 'My Plan',
  content: '# Plan\n\n...',
  document_type: 'plan',
  created_by: 'user-123',
});

// Connect for real-time collaboration
client.connect(doc.id);
```

## Protocol

### WebSocket Messages

**Client → Server:**
- `{ type: 'ping' }` - Heartbeat
- `{ type: 'edit', operation: { operation_type, position, content, length?, version } }` - Edit operation
- `{ type: 'cursor', position, selection_end? }` - Cursor update
- `{ type: 'presence', status: 'active' | 'idle' | 'away' }` - Presence update

**Server → Client:**
- `{ type: 'pong' }` - Heartbeat response
- `{ type: 'snapshot', document }` - Initial document state
- `{ type: 'operation', operation, document }` - Confirmed operation broadcast
- `{ type: 'cursor', user_id, position, selection_end? }` - Remote cursor
- `{ type: 'presence', user_id, status }` - Remote presence
- `{ type: 'error', code, message, ... }` - Error (including VERSION_CONFLICT)

### Strong Consistency

The server enforces version equality:
1. Client sends edit with `version` (the version they're editing from)
2. Server checks `version == document.version`
3. If mismatch → `VERSION_CONFLICT` error with current document state
4. Client rebases and retries

## Development

```bash
cd packages/collab-client
npm install
npm run build      # Build with tsup
npm run dev        # Watch mode
npm run typecheck  # Type checking
npm run test       # Run tests
```
