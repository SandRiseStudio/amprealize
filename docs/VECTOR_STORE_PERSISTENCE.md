# Vector Store Persistence Strategy

> **Status:** Architecture decision document for BehaviorRetriever semantic index storage
> **Last Updated:** 2025-10-22
> **Owner:** Engineering

## Executive Summary

The BehaviorRetriever semantic index requires persistent storage for FAISS vectors and behavior metadata to enable fast startup, cross-session consistency, and production scalability. This document evaluates two primary strategies—**filesystem persistence** (current implementation) vs **PostgreSQL with pgvector extension**—and provides a migration path and production recommendation.

## Current Implementation: Filesystem Persistence

### Architecture

**Index Storage:**
- **Location:** `~/.amprealize/data/behavior_index.faiss` (FAISS IndexFlatIP binary)
- **Metadata:** `~/.amprealize/data/behavior_index.json` (behavior IDs, cached behavior snapshots, model name, updated_at timestamp)
- **Format:** FAISS native binary format + JSON sidecar

**Lifecycle:**
- **Build:** `BehaviorRetriever.build_index()` creates embeddings via BGE-M3, normalizes L2, writes to FAISS IndexFlatIP
- **Load:** `BehaviorRetriever._load_index()` reads `.faiss` + `.json` on initialization if files exist
- **Persist:** `BehaviorRetriever._persist_index()` writes updated index after rebuild
- **Trigger:** Automatic rebuild on behavior approval via `BehaviorService.approve_behavior()` hook

### Pros

✅ **Zero infrastructure overhead** – No database required; works out-of-box
✅ **Fast local development** – Index loads in <50ms for 1K behaviors
✅ **Simple deployment** – Single-node Python process; no connection pooling
✅ **FAISS native performance** – Direct binary format optimized for similarity search
✅ **Portable** – Index files can be copied/distributed for reproducible environments

### Cons

❌ **No multi-node consistency** – Each process maintains separate index copy
❌ **Manual synchronization** – Horizontal scaling requires custom replication logic
❌ **No transactional integrity** – Metadata JSON and FAISS binary can drift on partial writes
❌ **Limited observability** – No SQL query logs or index health metrics
❌ **Storage inefficiency** – Duplicate indexes across dev/staging/prod environments

### Scalability Limits

- **1K behaviors:** ~5 MB index, <50ms load time ✅
- **10K behaviors:** ~50 MB index, ~200ms load time ✅
- **100K+ behaviors:** Filesystem approach breaks down; requires distributed storage

---

## Alternative: PostgreSQL + pgvector Extension

### Architecture

**Database Schema:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE behavior_embeddings (
    behavior_id UUID PRIMARY KEY,
    version VARCHAR(50) NOT NULL,
    embedding vector(1024),  -- BGE-M3 dimension
    instruction TEXT,
    name VARCHAR(255),
    description TEXT,
    tags TEXT[],
    role_focus VARCHAR(50),
    metadata JSONB,
    citation_label VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_behavior FOREIGN KEY (behavior_id)
        REFERENCES behaviors(behavior_id) ON DELETE CASCADE
);

CREATE INDEX ON behavior_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);  -- Tune based on dataset size
```

**Retrieval Query:**
```python
# Semantic search via pgvector cosine similarity
query_embedding = model.encode([query_text], convert_to_numpy=True)[0]
results = session.execute(
    """
    SELECT behavior_id, name, instruction,
           1 - (embedding <=> :query_vec) AS similarity
    FROM behavior_embeddings
    WHERE status = 'APPROVED'
    ORDER BY embedding <=> :query_vec
    LIMIT :top_k
    """,
    {"query_vec": query_embedding.tolist(), "top_k": top_k}
).fetchall()
```

### Pros

✅ **Multi-node consistency** – Single source of truth for distributed API/worker fleet
✅ **Transactional integrity** – ACID guarantees for embedding updates
✅ **SQL observability** – Query logs, index statistics, performance monitoring via pgAdmin/Datadog
✅ **Unified storage** – Behaviors + embeddings in single database; simpler backups
✅ **Horizontal scaling** – Read replicas, connection pooling via PgBouncer
✅ **PostgreSQL ecosystem** – Leverage existing HA setup, replication, point-in-time recovery

### Cons

❌ **Infrastructure dependency** – Requires PostgreSQL 12+ with pgvector extension
❌ **Initial complexity** – Schema migration, connection management, query tuning
❌ **Performance overhead** – Network latency (~5-10ms) vs in-memory FAISS (<1ms)
❌ **Extension availability** – Not all managed Postgres providers support pgvector (check AWS RDS, GCP Cloud SQL, Azure)
❌ **Index rebuild cost** – Database writes slower than filesystem for bulk updates

### Scalability Profile

- **1K behaviors:** ~100ms query latency (network + DB), acceptable ✅
- **10K behaviors:** IVFFlat index required; ~150ms query latency ✅
- **100K+ behaviors:** HNSW index recommended; ~200ms P95 latency, scales to millions ✅

---

## Hybrid Approach: Best of Both Worlds

### Strategy

1. **Development/CI:** Filesystem persistence (current implementation)
2. **Staging/Production:** PostgreSQL + pgvector with warm cache

### Implementation

**Cache Layer:**
```python
class BehaviorRetriever:
    def __init__(self, ..., use_database: bool = False, db_session: Optional[Session] = None):
        self._use_database = use_database
        self._db_session = db_session
        if not use_database:
            self._load_index()  # Filesystem path
        else:
            self._warm_cache_from_db()  # Load top 1K behaviors into FAISS in-memory
```

**Rebuild Hook:**
```python
def _persist_index(self) -> None:
    if self._use_database and self._db_session:
        # Write embeddings to PostgreSQL
        self._write_to_database()
    else:
        # Write to filesystem (current logic)
        faiss.write_index(self._index, str(self._index_path))
        # ... JSON metadata
```

### Benefits

✅ Developers get zero-setup local experience
✅ Production gets multi-node consistency + observability
✅ Gradual migration path (filesystem → database toggle via config)
✅ Fallback to filesystem if database unavailable (graceful degradation)

---

## Migration Path

### Phase 1: Preparation (Week 1)
- [ ] Add `pgvector` extension to production PostgreSQL (check version ≥ 0.5.0)
- [ ] Create `behavior_embeddings` table schema in migrations
- [ ] Add `use_database` configuration flag to BehaviorRetriever (`VECTOR_STORE_BACKEND=filesystem|postgres`)
- [ ] Implement database write path in `_persist_index()`

### Phase 2: Dual-Write (Week 2)
- [ ] Enable dual-write mode: persist to both filesystem AND database
- [ ] Backfill existing filesystem index to `behavior_embeddings` table
- [ ] Validate data consistency via SQL queries vs FAISS results
- [ ] Monitor query latency and index size in production

### Phase 3: Read Cutover (Week 3)
- [ ] Implement database read path in `_embedding_retrieve()`
- [ ] Deploy canary: 10% traffic reads from database, 90% from filesystem
- [ ] Validate P95 latency stays <100ms (vs <100ms FAISS target)
- [ ] Gradually increase to 100% database reads

### Phase 4: Cleanup (Week 4)
- [ ] Remove filesystem write path (keep as fallback only)
- [ ] Archive `.faiss` + `.json` files for emergency rollback
- [ ] Update documentation (`RETRIEVAL_ENGINE_PERFORMANCE.md`, runbooks)
- [ ] Monitor for 1 week; remove fallback code if stable

---

## Production Recommendation

### Immediate (Milestone 2 Phase 1 Complete)
**Continue with filesystem persistence** for the following reasons:
- Current implementation is production-ready for ≤10K behaviors
- Zero infrastructure changes required for BCI rollout
- Meets <100ms P95 latency target in single-node deployment
- Simplifies external beta and early adoption

### Future (Milestone 3 or 100K+ behaviors)
**Migrate to PostgreSQL + pgvector** when:
- Multi-region deployment requires index consistency
- Behavior count exceeds 10K (check via `SELECT COUNT(*) FROM behaviors WHERE status='APPROVED'`)
- Observability requirements demand SQL query logs
- Horizontal scaling of API/worker fleet is planned

### Configuration Flag
```bash
# .env or environment variables
VECTOR_STORE_BACKEND=filesystem  # Default for dev/single-node
# VECTOR_STORE_BACKEND=postgres  # Enable for production multi-node
```

---

## Performance Comparison

| Metric | Filesystem (FAISS) | PostgreSQL (pgvector) | Target |
|--------|-------------------|----------------------|--------|
| Index Load (1K behaviors) | ~50ms | ~100ms (network + query) | <100ms ✅ |
| Retrieval P50 (top-10) | <5ms | ~20ms | <50ms ✅ |
| Retrieval P95 (top-10) | <10ms | ~50ms | <100ms ✅ |
| Index Rebuild (1K behaviors) | ~500ms | ~2s (bulk insert) | <5s ✅ |
| Multi-node consistency | ❌ Manual sync | ✅ Automatic | Required for scale |
| Storage overhead | 5 MB/node | 5 MB (shared) | Minimize |

---

## Security Considerations

### Filesystem
- Index files at `~/.amprealize/data/` must be readable only by application user
- Metadata JSON contains behavior instructions; ensure proper ACLs
- Backup strategy: include `.faiss` + `.json` in nightly snapshots

### PostgreSQL
- Embedding vectors contain no PII but are sensitive IP (behavior instructions)
- Use `SSL/TLS` for database connections in production
- Apply row-level security if multi-tenant deployment planned
- Encrypt backups containing `behavior_embeddings` table

---

## Cost Analysis

### Filesystem
- **Storage:** ~5 MB/1K behaviors × number of nodes (e.g., 3 nodes = 15 MB)
- **Compute:** Included in application server memory/disk
- **Operations:** Zero incremental cost

### PostgreSQL
- **Storage:** ~5 MB/1K behaviors (shared across nodes)
- **Compute:** Existing PostgreSQL instance; minimal CPU overhead (<5%)
- **Extension:** pgvector is open-source (no licensing cost)
- **Operations:** Included in existing database backups/monitoring

**Verdict:** Filesystem cheaper for single-node; PostgreSQL cheaper at scale (shared storage).

---

## Testing Strategy

### Filesystem (Current)
- ✅ Unit tests cover index build/load/persist
- ✅ Parity tests validate retrieval accuracy
- ✅ Integration tests confirm auto-rebuild on approval

### PostgreSQL (Future)
- [ ] Schema migration tests (up/down)
- [ ] Bulk insert performance benchmarks
- [ ] Query latency regression tests (compare vs FAISS baseline)
- [ ] Multi-node consistency tests (simulate concurrent writes)
- [ ] Failover tests (database down → fallback to keyword search)

---

## References

- **pgvector Documentation:** https://github.com/pgvector/pgvector
- **FAISS Documentation:** https://github.com/facebookresearch/faiss
- **BGE-M3 Model:** https://huggingface.co/BAAI/bge-m3
- **amprealize Contracts:** `contracts/MCP_SERVER_DESIGN.md` § 8.2 (BehaviorRetriever Architecture)
- **Performance Targets:** `contracts/RETRIEVAL_ENGINE_PERFORMANCE.md`

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-10-22 | **Adopt filesystem persistence for Milestone 2** | Simplicity, zero infrastructure overhead, meets latency targets for ≤10K behaviors |
| TBD | Evaluate PostgreSQL migration | Trigger: behavior count >10K OR multi-region deployment required |

_Last Updated: 2025-10-22_
