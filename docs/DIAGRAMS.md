# Architecture & Flow Diagrams

> **SYNTHETIC DEMO — NOT A REAL BANKING SYSTEM.**
> All banks, customers, accounts, amounts, services, metrics and logs are fictional.

## Table of contents

1. [System architecture](#1-system-architecture)
2. [Request flow](#2-request-flow)
3. [Investigation workflow (LangGraph state machine)](#3-investigation-workflow-langgraph-state-machine)
4. [Governed RAG pipeline](#4-governed-rag-pipeline)
5. [Action execution with approval](#5-action-execution-with-approval)
6. [Audit hash chain](#6-audit-hash-chain)
7. [Authentication & authorization flow](#7-authentication--authorization-flow)
8. [Evaluation & release gate](#8-evaluation--release-gate)
9. [Data model (ERD)](#9-data-model-erd)
10. [Deployment topology](#10-deployment-topology)

---

## 1. System architecture

```mermaid
graph TB
    subgraph Browser["Browser (SPA)"]
        UI["React 19 + Vite + Tailwind<br/>14 pages + guided demo<br/>TanStack Query + React Router"]
        AuthCtx["AuthContext<br/>sessionStorage JWT<br/>permission gating"]
        APIClient["Typed API Client<br/>bearer auth, SSE reader<br/>error envelope parsing"]
    end

    subgraph Backend["FastAPI Backend"]
        subgraph API["API Layer"]
            MW["Middleware<br/>CORS, security headers<br/>request ID, body limits"]
            Routes["54 REST endpoints<br/>+ SSE streaming"]
        end

        subgraph Core["Core Services"]
            AuthService["Auth Service<br/>Argon2 + JWT + revocation"]
            PolicyEngine["Policy Engine<br/>deterministic allow/deny/approval<br/>NEVER in a prompt"]
            AuditService["Audit Service<br/>append-only hash chain<br/>DB triggers block UPDATE/DELETE"]
        end

        subgraph AI["AI Layer"]
            Gateway["Model Gateway<br/>mock + OpenAI-compatible<br/>retries, jitter, circuit breaker"]
            PromptReg["Prompt Registry<br/>versioned, typed outputs"]
            Workflow["LangGraph Workflow<br/>7 agents, bounded<br/>resumable approval"]
        end

        subgraph RAG["RAG Layer"]
            Chunker["Chunker<br/>structure-aware"]
            Embedder["Embeddings<br/>mock (hash) or OpenAI"]
            Retriever["Hybrid Retriever<br/>vector + BM25 + RRF<br/>authz-filtered"]
            Injection["Injection Defense<br/>neutralize at ingest + retrieve"]
        end

        subgraph Actions["Action Layer"]
            ToolReg["Tool Registry<br/>typed, allowlisted"]
            ActionSvc["Action Service<br/>idempotent (CAS)<br/>rollback + verify"]
            ApprovalSvc["Approval Service<br/>SoD, expiry, hash-bound"]
        end

        subgraph Eval["Evaluation"]
            Harness["Evaluation Harness<br/>versioned dataset<br/>14 metrics"]
            Gate["Release Gate<br/>required + warning thresholds"]
            Promo["Promotion Workflow<br/>dev → staging → production_ready"]
        end
    end

    subgraph Data["Data Layer"]
        DB[("Database<br/>SQLite (local)<br/>PostgreSQL + pgvector (Docker)")]
        Seed["Synthetic Seed Data<br/>2 tenants, 9 users<br/>59 incidents, 16 docs"]
    end

    UI --> AuthCtx
    UI --> APIClient
    APIClient -->|"HTTPS / SSE<br/>/api/* proxy"| MW
    MW --> Routes
    Routes --> AuthService
    Routes --> PolicyEngine
    Routes --> AuditService
    Routes --> Workflow
    Routes --> Retriever
    Routes --> ActionSvc
    Routes --> ApprovalSvc
    Routes --> Harness
    Workflow --> Gateway
    Workflow --> PromptReg
    Workflow --> Retriever
    Workflow --> ToolReg
    Workflow --> ActionSvc
    Workflow --> PolicyEngine
    Workflow --> AuditService
    Retriever --> Chunker
    Retriever --> Embedder
    Retriever --> Injection
    ActionSvc --> ToolReg
    ActionSvc --> PolicyEngine
    ActionSvc --> AuditService
    Harness --> Gate
    Gate --> Promo
    AuthService --> DB
    PolicyEngine --> DB
    AuditService --> DB
    Retriever --> DB
    ActionSvc --> DB
    Seed --> DB
```

### Key design principle

```
┌──────────────────────────────────────────────────────────────┐
│  THE LLM IS NEVER THE AUTHORIZATION BOUNDARY                  │
│                                                              │
│  Model proposes ──► Policy Engine disposes                   │
│                                                              │
│  ┌──────────┐     ┌──────────────┐     ┌───────────────┐    │
│  │  LLM     │     │ Policy Engine│     │  Audit Log    │    │
│  │ proposes │────►│ decides      │────►│  records      │    │
│  │ actions  │     │ allow/deny/  │     │  every        │    │
│  │          │     │ approval     │     │  decision     │    │
│  └──────────┘     └──────────────┘     └───────────────┘    │
│       │                   │                                  │
│       ▼                   ▼                                  │
│  ┌──────────┐     ┌──────────────┐                          │
│  │ Pydantic │     │ Tool Registry│                          │
│  │ validates│     │ allowlisted  │                          │
│  │ output   │     │ typed params │                          │
│  └──────────┘     └──────────────┘                          │
│                                                              │
│  Even if the model is fully compromised via prompt injection,│
│  it CANNOT execute unauthorized actions.                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Request flow

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant V as Vite Dev Server
    participant F as FastAPI
    participant A as Auth Service
    participant P as Policy Engine
    participant DB as Database

    U->>V: GET /incidents (with JWT in sessionStorage)
    V->>F: GET /api/incidents (proxy, Authorization: Bearer <jwt>)
    F->>F: Middleware: CORS, security headers, request ID
    F->>A: Validate JWT (signature, expiry, revocation list)
    A->>DB: Check revocation list
    DB-->>A: Not revoked
    A-->>F: User context (username, role, tenant_id, permissions)
    F->>P: Check permission: incidents:read
    P-->>F: Allowed
    F->>DB: Query incidents WHERE tenant_id = user.tenant_id
    DB-->>F: Incident list (tenant-filtered)
    F-->>V: 200 OK + JSON + security headers
    V-->>U: JSON response
```

### SSE (Server-Sent Events) flow for live investigation updates

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant F as FastAPI
    participant W as Workflow Runner
    participant DB as Database

    U->>F: GET /investigations/{id}/events (Accept: text/event-stream)
    F->>DB: Load investigation state + events since Last-Event-ID
    DB-->>F: State + pending events
    F-->>U: SSE: existing events (replay)
    
    loop While investigation is active
        W->>DB: Persist new event
        DB-->>F: Notify (poll or event)
        F-->>U: SSE: data: {event JSON}\n\n
    end
    
    W->>DB: Mark investigation completed
    F-->>U: SSE: event: end\ndata: {final state}\n\n
    F-->>U: Connection closed
```

---

## 3. Investigation workflow (LangGraph state machine)

```mermaid
stateDiagram-v2
    [*] --> Queued: POST /incidents/{id}/investigations

    Queued --> Orchestrator: Background runner picks up

    state "Bounded by:\n• max steps\n• max tool calls/step\n• token budget\n• per-step timeout\n• total timeout" as Bounds

    Orchestrator --> Triage: Step 1
    Triage --> Orchestrator: Classified

    Orchestrator --> EvidenceRetrieval: Step 2
    state EvidenceRetrieval {
        [*] --> BuildQuery
        BuildQuery --> HybridSearch: authz-filtered
        HybridSearch --> RRFusion: vector + BM25
        RRFusion --> Rerank: lexical + trust
        Rerank --> Neutralize: injection defense
        Neutralize --> SufficiencyCheck
        SufficiencyCheck --> [*]: enough evidence
        SufficiencyCheck --> [*]: abstain (insufficient)
    }
    EvidenceRetrieval --> Orchestrator: Evidence + citations

    Orchestrator --> Diagnostic: Step 3
    Diagnostic --> Orchestrator: Tool results (read-only tools)

    Orchestrator --> RemediationPlanner: Step 4
    RemediationPlanner --> Orchestrator: Proposed actions

    Orchestrator --> GovernanceReview: Step 5
    GovernanceReview --> Orchestrator: Risk assessment

    Orchestrator --> PolicyGate: Step 6
    PolicyGate --> PolicyGate: Deterministic decision\n(NOT an LLM)
    
    PolicyGate --> AutoExecute: risk = low\nallow
    PolicyGate --> AwaitingApproval: risk = medium/high\nrequire approval
    PolicyGate --> Denied: prohibited action\nor policy violation

    AwaitingApproval --> [*]: Persisted state\n(waiting for human)

    AutoExecute --> SimulatedExecutor
    SimulatedExecutor --> Verification
    Verification --> Orchestrator: Resolved

    Denied --> Orchestrator: Log denial

    Orchestrator --> FinalReport: All steps complete
    FinalReport --> [*]: Investigation completed

    note right of AwaitingApproval
        When approval is granted:
        1. Re-load persisted state
        2. Re-check approval scope
        3. Re-check approval expiry
        4. Re-check action hash
        5. Resume from SimulatedExecutor
    end note

    note right of PolicyGate
        The policy engine uses:
        - action name (allowlist)
        - parameters (Pydantic-validated)
        - risk level (catalog)
        - user role (RBAC)
        - tenant scope
        
        It does NOT parse model output.
        It keeps working when the model is down.
    end note
```

### Workflow bounds and degraded mode

```mermaid
flowchart TD
    Start[Investigation starts] --> CheckProvider{Model provider available?}
    
    CheckProvider -->|"Yes"| NormalMode[Normal mode<br/>LLM agents run normally]
    CheckProvider -->|"No"| CircuitBreaker[Circuit breaker opens<br/>after N failures]
    
    CircuitBreaker --> DegradedMode[Degraded mode<br/>deterministic fallbacks<br/>policy engine still works<br/>audit still records]
    
    NormalMode --> StepBudget{Step / tool / token<br/>budget exceeded?}
    DegradedMode --> StepBudget
    
    StepBudget -->|"No"| Continue[Continue investigation]
    StepBudget -->|"Yes"| Interrupt[Interrupt + persist state<br/>can be resumed]
    
    Continue --> Timeout{Timeout?}
    Timeout -->|"No"| Continue
    Timeout -->|"Yes"| Interrupt
```

---

## 4. Governed RAG pipeline

```mermaid
flowchart LR
    subgraph Ingestion["Ingestion (admin/manager only)"]
        Upload[Upload document<br/>md, txt, pdf]
        Scan1[Scan for injection<br/>neutralize + flag]
        Chunk[Structure-aware<br/>chunking]
        Hash[Content hash<br/>deduplication]
        Embed[Generate embeddings<br/>mock or OpenAI]
        Store[Store in vector DB<br/>pgvector or SQLite]
        Upload --> Scan1 --> Chunk --> Hash --> Embed --> Store
    end

    subgraph Retrieval["Retrieval (authorized users)"]
        Query[User query]
        AuthzFilter[Authorization filters<br/>tenant_id<br/>classification ≤ clearance<br/>role in allowed_roles]
        VectorSearch[Vector search<br/>cosine similarity]
        BM25Search[BM25 keyword<br/>term frequency]
        RRF[Reciprocal Rank Fusion<br/>combine rankings]
        Rerank[Lexical reranking<br/>+ source-trust weighting<br/>unverified down-ranked]
        Scan2[Scan for injection<br/>neutralize at retrieval]
        Sufficient{Sufficient<br/>evidence?}
        Results[Results with citations<br/>section path + chunk hash]
        Abstain[Abstain<br/>do not hallucinate]
        
        Query --> AuthzFilter
        AuthzFilter --> VectorSearch
        AuthzFilter --> BM25Search
        VectorSearch --> RRF
        BM25Search --> RRF
        RRF --> Rerank
        Rerank --> Scan2
        Scan2 --> Sufficient
        Sufficient -->|"Yes"| Results
        Sufficient -->|"No"| Abstain
    end

    Store -.->|"indexed chunks"| VectorSearch
    Store -.->|"chunk text"| BM25Search
```

### Authorization filtering (before ranking, not after)

```mermaid
flowchart TD
    Q[User query] --> F1{Tenant filter<br/>WHERE tenant_id = user.tenant_id}
    F1 -->|Filtered| F2{Classification filter<br/>WHERE classification ≤ user.clearance}
    F2 -->|Filtered| F3{Role filter<br/>WHERE allowed_roles ∋ user.role}
    F3 -->|Filtered pool| R[Ranking pipeline<br/>vector + BM25 + RRF]
    R --> Results[Authorized results only]
    
    note1[Unauthorized chunks<br/>NEVER enter ranking]
    F1 -.-> note1
    F2 -.-> note1
    F3 -.-> note1
```

---

## 5. Action execution with approval

```mermaid
sequenceDiagram
    participant W as Workflow
    participant P as Policy Engine
    participant AS as Approval Service
    participant A as Action Service
    participant DB as Database
    participant AU as Audit Service
    participant H as Human Approver

    W->>P: Evaluate action (tool, params, risk, user)
    
    alt Prohibited action
        P-->>W: DENY (prohibited)
        W->>AU: Record denial
    else Low risk (auto-approved)
        P-->>W: ALLOW
        W->>A: Execute (idempotent)
    else Medium/High risk
        P-->>W: REQUIRE_APPROVAL
        W->>AS: Create approval request
        AS->>DB: Store approval (status=pending, action_hash, expiry)
        AS->>AU: Record approval request
        W-->>W: Pause (persist state)
        
        Note over H: Human reviews evidence,<br/>policy explanation,<br/>and action hash
        
        H->>AS: Approve (with confirmation + reason)
        
        alt Approver is requester (high-risk)
            AS-->>H: 403 Forbidden (SoD violation)
        else Approval expired
            AS-->>H: 410 Gone (expired)
        else Valid approval
            AS->>DB: Update approval (status=approved)
            AS->>AU: Record approval
            AS-->>W: Resume investigation
            
            W->>P: Re-check (scope, expiry, hash)
            P-->>W: ALLOW (re-verified)
            
            W->>A: Execute with CAS
            A->>DB: CAS: status pending_approval → executing
            A->>DB: Snapshot state (for rollback)
            A->>DB: Execute simulated action
            A->>DB: CAS: status executing → succeeded/failed
            
            alt Action succeeded
                A->>A: Post-action verification
                A->>AU: Record success + verification
            else Action failed
                A->>A: Rollback (restore snapshot)
                A->>AU: Record failure + rollback
            end
        end
    end
```

### Idempotency via Compare-And-Swap (CAS)

```mermaid
flowchart TD
    Start[Execute action] --> CAS1{CAS: status == pending_approval?}
    CAS1 -->|"Yes"| Set1[Set status = executing<br/>atomic]
    CAS1 -->|"No (already executing)"| Skip[Skip - already in progress]
    CAS1 -->|"No (already done)"| Skip2[Skip - already completed]
    
    Set1 --> Snapshot[Capture state snapshot<br/>for rollback]
    Snapshot --> Execute[Execute simulated action<br/>against demo state]
    Execute --> Verify[Post-action verification]
    
    Verify --> CAS2{CAS: status == executing?}
    CAS2 -->|"Yes"| Set2[Set status = succeeded<br/>record verification]
    CAS2 -->|"No (concurrent modification)"| Abort[Abort - state changed]
    
    Set2 --> Done[Action complete]
    
    Verify -->|Verification failed| CAS3{CAS: status == executing?}
    CAS3 -->|"Yes"| Rollback[Rollback: restore snapshot]
    CAS3 -->|"No"| Abort
    Rollback --> Set3[Set status = rolled_back]
    Set3 --> Done
```

---

## 6. Audit hash chain

```mermaid
flowchart LR
    E1[Event 1<br/>{"action":"login",...}] --> H1["hash_1 = SHA-256<br/>('' + canonical(event_1))"]
    H1 --> E2[Event 2<br/>{"action":"policy_decision",...}]
    E2 --> H2["hash_2 = SHA-256<br/>(hash_1 + canonical(event_2))"]
    H2 --> E3[Event 3<br/>{"action":"approval",...}]
    E3 --> H3["hash_3 = SHA-256<br/>(hash_2 + canonical(event_3))"]
    H3 --> E4[Event 4<br/>{"action":"execution",...}]
    E4 --> H4["hash_4 = SHA-256<br/>(hash_3 + canonical(event_4))"]
    H4 --> E5[Event N<br/>...]
    
    style H1 fill:#e1f5e1
    style H2 fill:#e1f5e1
    style H3 fill:#e1f5e1
    style H4 fill:#e1f5e1
```

```mermaid
flowchart TD
    Verify[Verify hash chain] --> Read[Read all events<br/>ORDER BY sequence ASC]
    Read --> Loop{For each event}
    Loop --> Compute[Recompute:<br/>expected = SHA-256<br/>(prev_hash + canonical(event))]
    Compute --> Compare{expected == stored_hash?}
    Compare -->|"Yes"| Next[Next event]
    Next --> Loop
    Compare -->|"No"| Invalid["CHAIN INVALID<br/>at event #N<br/>tampering detected"]
    Loop -->|"All match"| Valid["CHAIN VALID<br/>all events verified"]
    
    style Valid fill:#e1f5e1
    style Invalid fill:#fde1e1
```

### Database-level append-only enforcement

```mermaid
flowchart TD
    App[Application code<br/>INSERT only] --> DB[(audit_events table)]
    ORM[ORM layer<br/>no UPDATE/DELETE methods] --> DB
    Trigger["DB Triggers<br/>BEFORE UPDATE → RAISE<br/>BEFORE DELETE → RAISE"] --> DB
    
    style Trigger fill:#fde1e1
    note["Defense in depth:<br/>Even if ORM is bypassed,<br/>triggers block modification"]
    Trigger -.-> note
```

---

## 7. Authentication & authorization flow

```mermaid
flowchart TD
    Login[User submits<br/>username + password] --> Validate[Auth Service<br/>Argon2 verify]
    Validate -->|Invalid| Reject[401 Unauthorized]
    Validate -->|Valid| JWT[Generate JWT<br/>30-min expiry<br/>HS256 signed]
    JWT --> Revoke[Store in revocation<br/>list on logout]
    JWT --> Session[Store in sessionStorage<br/>NOT cookies<br/>NOT localStorage]
    Session --> Requests[All API requests<br/>Authorization: Bearer JWT]
    
    Requests --> MW[Middleware<br/>extract + validate JWT]
    MW -->|Invalid/expired/revoked| Reject2[401 Unauthorized<br/>clear session]
    MW -->|Valid| Context[User context<br/>username, role,<br/>tenant_id, permissions]
    Context --> PermCheck{Permission check<br/>per endpoint}
    PermCheck -->|Allowed| Handler[Route handler]
    PermCheck -->|Denied| Forbidden[403 Forbidden]
    
    Handler --> TenantFilter[Tenant isolation<br/>WHERE tenant_id = user.tenant_id]
    TenantFilter --> ClassFilter[Classification filter<br/>WHERE classification ≤ clearance]
    ClassFilter --> Response[200 OK]
```

### RBAC decision matrix

```mermaid
flowchart LR
    subgraph Roles
        DA[demo_admin]
        OM[ops_manager]
        OA[ops_analyst]
        AU[auditor]
        RO[read_only]
    end

    subgraph Permissions["27 permissions"]
        P1[dashboard:read]
        P2[investigations:start]
        P3[approvals:decide]
        P4[knowledge:ingest]
        P5[demo:reset]
        P6["... 22 more"]
    end

    DA -->|all 27| Permissions
    OM -->|22| Permissions
    OA -->|16| Permissions
    AU -->|12| Permissions
    RO -->|8| Permissions
```

---

## 8. Evaluation & release gate

```mermaid
flowchart TD
    Run[Run evaluation<br/>on versioned dataset] --> Cases[Execute test cases<br/>retrieval, citation, tool,<br/>injection, root_cause,<br/>abstention, policy, claims, workflow]
    
    Cases --> Metrics[Compute 14 metrics<br/>recall@5, MRR, validation,<br/>injection resistance,<br/>root cause accuracy,<br/>citation coverage,<br/>policy compliance, ...]
    
    Metrics --> Gate{Release gate}
    
    Gate -->|All required pass| Eligible[Bundle eligible<br/>for promotion]
    Gate -->|Any required fails| Blocked[Promotion BLOCKED<br/>report failures]
    
    Eligible --> Promo[Promotion workflow]
    Promo --> Dev[development]
    Dev --> Staging[staging]
    Staging --> Prod[production_ready]
    
    Prod --> RB[Rollback if needed<br/>revert to previous bundle]
    
    note1["Required metrics (block):<br/>recall@5 ≥ 0.90<br/>MRR ≥ 0.80<br/>unauthorized_leaks == 0<br/>validation_accuracy ≥ 0.95<br/>injection_resistance ≥ 0.95<br/>root_cause ≥ 0.85<br/>policy_compliance == 1.0<br/>citation_coverage ≥ 0.90<br/>prohibited_executions == 0"]
    Gate -.-> note1
    
    note2["Warning metrics (report):<br/>failure_rate ≤ 0.05<br/>latency_p95 ≤ 30s"]
    Gate -.-> note2
```

---

## 9. Data model (ERD)

```mermaid
erDiagram
    TENANT ||--o{ USER : has
    TENANT ||--o{ INCIDENT : owns
    TENANT ||--o{ KNOWLEDGE_DOCUMENT : owns
    TENANT ||--o{ SERVICE : has
    
    USER ||--o{ INVESTIGATION : starts
    USER ||--o{ APPROVAL : requests
    USER ||--o{ APPROVAL : decides
    USER ||--o{ AUDIT_EVENT : performs
    
    INCIDENT ||--o{ INVESTIGATION : has
    INCIDENT ||--o{ INCIDENT_LOG : has
    INCIDENT }o--|| SERVICE : affects
    INCIDENT }o--o{ SERVICE : depends_on
    
    INVESTIGATION ||--o{ INVESTIGATION_EVENT : produces
    INVESTIGATION ||--o{ ACTION : proposes
    INVESTIGATION ||--o{ DIAGNOSIS : produces
    INVESTIGATION ||--o{ EVIDENCE : cites
    
    ACTION ||--|| APPROVAL : requires
    ACTION ||--o{ VERIFICATION_RESULT : verified_by
    
    KNOWLEDGE_DOCUMENT ||--o{ KNOWLEDGE_CHUNK : chunked_into
    KNOWLEDGE_CHUNK ||--o{ EVIDENCE : cited_as
    
    EVALUATION_RUN ||--o{ EVALUATION_CASE_RESULT : contains
    PROMOTION ||--|| EVALUATION_RUN : based_on

    TENANT {
        string id PK
        string name
        string slug
        bool is_active
    }
    
    USER {
        string id PK
        string tenant_id FK
        string username UK
        string display_name
        string email
        string role
        string password_hash
        string clearance
        bool is_demo_account
        datetime created_at
    }
    
    INCIDENT {
        string id PK
        string tenant_id FK
        string incident_number
        string title
        string severity
        string status
        string category
        string risk_level
        string service_id FK
        json attributes
        datetime created_at
        datetime resolved_at
    }
    
    INVESTIGATION {
        string id PK
        string incident_id FK
        string started_by FK
        string status
        string outcome
        string risk_level
        string model_mode
        string workflow_version
        int step_count
        json state
        datetime created_at
        datetime completed_at
    }
    
    ACTION {
        string id PK
        string investigation_id FK
        string tool_name
        json parameters
        string target_resource
        string risk_level
        string status
        string idempotency_key
        string action_hash
        json snapshot
        json verification_result
        datetime created_at
        datetime executed_at
    }
    
    APPROVAL {
        string id PK
        string action_id FK
        string requested_by FK
        string decided_by FK
        string status
        string risk_level
        string target_resource
        string action_hash
        string approve_block_reason
        string reject_block_reason
        datetime expires_at
        datetime decided_at
    }
    
    AUDIT_EVENT {
        string id PK
        string tenant_id FK
        int sequence
        string event_type
        string actor
        string action
        json details
        string prev_hash
        string hash
        datetime created_at
    }
    
    KNOWLEDGE_DOCUMENT {
        string id PK
        string tenant_id FK
        string doc_id
        string title
        string classification
        json allowed_roles
        string source_trust
        int injection_flags
        datetime ingested_at
    }
    
    KNOWLEDGE_CHUNK {
        string id PK
        string document_id FK
        string content_hash
        text content
        string section_path
        vector embedding
        int token_count
    }
```

---

## 10. Deployment topology

### Local development (current setup)

```mermaid
flowchart LR
    subgraph LocalMachine["Local Machine"]
        subgraph Terminal1["Terminal 1"]
            Backend["FastAPI<br/>port 8000<br/>SQLite + mock provider"]
        end
        subgraph Terminal2["Terminal 2"]
            Vite["Vite Dev Server<br/>port 5173<br/>proxy /api → :8000"]
        end
        Browser["Browser<br/>http://127.0.0.1:5173"]
    end
    
    Browser -->|"http://127.0.0.1:5173"| Vite
    Vite -->|"/api/* proxy"| Backend
    Backend -->|"SQLite file"| DBFile[("backend/data/bankops.db")]
```

### Docker Compose (production-like)

```mermaid
flowchart LR
    subgraph Docker["Docker Compose Stack"]
        subgraph FrontendContainer["frontend container"]
            Nginx["Nginx<br/>port 80<br/>SPA + proxy"]
        end
        subgraph BackendContainer["backend container"]
            Uvicorn["Uvicorn<br/>port 8000<br/>FastAPI app"]
        end
        subgraph DBContainer["db container"]
            PG[("PostgreSQL 16<br/>+ pgvector<br/>HNSW index")]
        end
    end
    
    User["User browser"] -->|"http://localhost:80"| Nginx
    Nginx -->|"/api/* proxy"| Uvicorn
    Nginx -->|"/docs proxy"| Uvicorn
    Uvicorn -->|"SQL + vectors"| PG
```

### Vercel + separate backend (cloud)

```mermaid
flowchart LR
    subgraph Vercel["Vercel (frontend)"]
        Static["Static SPA<br/>CDN-distributed"]
        Redirects["vercel.json<br/>redirects /api/*"]
    end
    
    subgraph CloudBackend["Cloud backend (Railway/Fly/Render)"]
        CloudAPI["FastAPI container<br/>HTTPS"]
        CloudDB[("Managed PostgreSQL<br/>+ pgvector")]
    end
    
    User2["User browser"] -->|"HTTPS"| Static
    Static -->|"/api/* redirect"| CloudAPI
    CloudAPI -->|"SQL + vectors"| CloudDB
```
