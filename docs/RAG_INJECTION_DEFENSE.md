# RAG & Prompt-Injection Defense

## Governed RAG architecture

```
Query → Authorization filters (tenant, classification, role)
      → Hybrid retrieval (vector + BM25 with reciprocal-rank fusion)
      → Lexical reranking
      → Source-trust weighting (unverified sources down-ranked)
      → Injection neutralization (on every retrieved chunk)
      → Sufficiency check (enough evidence?)
      → Results with citations
```

### Chunking

- Structure-aware: splits on Markdown headings, paragraphs and sentence boundaries.
- Configurable chunk size (default: 1200 chars) and overlap (default: 200 chars).
- Each chunk records its section path, character count and estimated token count.
- Chunks are content-hashed (SHA-256) for deduplication.

### Embeddings

- **Mock provider:** Deterministic hash-based embeddings (no API key needed). Used for
  local development and evaluation.
- **OpenAI-compatible provider:** Uses `text-embedding-3-small` (1536d) by default.
  Configurable via environment variables.
- Embeddings are stored in pgvector (PostgreSQL) or as BLOBs in SQLite.

### Hybrid retrieval

- **Vector search:** Cosine similarity against the embedding store.
- **BM25 (keyword):** Term-frequency-based scoring over chunk text.
- **Fusion:** Reciprocal-rank fusion (RRF) combines the two ranked lists.
- **Reranking:** A lexical reranker boosts chunks with exact query-term matches.
- **Source trust:** Documents tagged `unverified` are down-weighted in reranking and
  labeled in results.

### Authorization filters

Retrieval is authorized **before** ranking, not after:

1. **Tenant filter:** Only documents belonging to the user's tenant.
2. **Classification filter:** Only documents at or below the user's clearance.
3. **Role filter:** Only documents whose `allowed_roles` include the user's role.

This prevents unauthorized data from ever entering the ranking pipeline.

### Sufficiency check

After retrieval, the system checks whether the results are sufficient to answer the query.
If not, the agent abstains rather than hallucinating. The sufficiency threshold is configurable.

### Citations

Every chunk returned includes a citation string (e.g., `RB-TEST-020 §2.1 ¶3`) that can be
traced back to the source document and section. The final report includes citations for
every claim.

## Prompt-injection defense

### Threat model

An adversary could attempt to inject instructions into:
- Knowledge documents (uploaded or seeded)
- Service logs (synthetic)
- Tool results (simulated)
- Analyst notes (free text)

The goal would be to trick the model into bypassing the policy engine, executing
unauthorized actions or leaking restricted data.

### Defense layers

1. **Ingestion-time neutralization:** When documents are chunked and indexed, each chunk
   is scanned for instruction-like patterns. Detected patterns are neutralized (wrapped in
   data delimiters) and flagged. The flag count is visible in the document list and index stats.

2. **Retrieval-time neutralization:** When chunks are retrieved, they are scanned again
   and neutralized before being passed to the agent. This catches injection that may have
   been added after ingestion (e.g., via re-indexing).

3. **System prompt:** The system prompt explicitly instructs the model to treat all
   retrieved content as data, not instructions. It also instructs the model to never
   attempt to execute actions, access external systems or reveal secrets.

4. **Policy engine independence:** The policy engine does not parse model output for
   authorization decisions. It uses the action name, parameters, risk level and user
   role — all of which are validated independently of the model.

5. **Typed tool calls:** The model can only call allowlisted tools with Pydantic-validated
   parameters. It cannot execute arbitrary code, SQL or shell commands.

6. **Output validation:** Agent outputs are validated through Pydantic schemas. Unexpected
   fields, unknown tools or invalid parameters are rejected.

### Injection pattern catalog

| Pattern ID | Description |
|---|---|
| `instruction_override` | "Ignore previous instructions", "disregard the above", etc. |
| `role_hijack` | "You are now...", "act as...", "pretend you are..." |
| `action_request` | "Execute...", "run...", "delete...", "transfer..." |
| `data_exfiltration` | "Send to...", "post to...", "call this URL..." |
| `credential_request` | "What is the password", "show me the API key" |
| `policy_bypass` | "Skip approval", "bypass the check", "ignore the policy" |
| `encoding_attack` | Base64-encoded instructions, unicode tricks |

### Testing

The evaluation harness includes injection-resistance test cases:
- Documents with embedded injection attempts are retrieved.
- The system is expected to neutralize them and not act on them.
- The injection-resistance metric is part of the release gate.

The synthetic knowledge base includes a dedicated injection-test document
(`RB-INJECT-001`) that contains various injection patterns. It is flagged at ingestion
and neutralized at retrieval.

## What this demo does NOT claim

- The injection defense is deterministic (pattern-based), not model-based. It catches
  known patterns but is not a complete defense against all possible injection techniques.
- A production system would need additional layers: output filtering, human review of
  high-risk actions, red-teaming and continuous evaluation.
- The mock provider does not test real model behavior. A live provider is needed to
  measure actual injection resistance.
