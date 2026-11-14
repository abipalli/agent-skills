# Repo Review Playbook

Use this reference when the main `repo-review` skill needs a deeper checklist, a worker prompt, or a synthesis template. Load only the relevant section.

## Review Dimensions

### Correctness

- Boundary values, empty inputs, max-size inputs, Unicode/path encoding, overflow, and time handling.
- Invariants across success, error, retry, cancellation, and cleanup paths.
- Copy-paste errors, stale references, wrong defaults, misleading comments, and unreachable branches.
- Behavior mismatches between implementation, docs, tests, and user-facing contracts.

### Security And Access Control

- Missing authentication or authorization, IDOR, confused-deputy flows, privilege escalation, and tenant isolation.
- Injection risks: SQL, command, template, LDAP, NoSQL, XSS, SSRF, path traversal, and open redirects.
- Unsafe file handling, deserialization, webhook verification, CORS, CSRF, rate limits, and abuse controls.
- Secrets in code, logs, config, telemetry, generated artifacts, or test fixtures.
- Crypto misuse: weak randomness, nonce reuse, bad password hashing, certificate validation bypasses.

### Data Integrity

- Transaction boundaries, isolation assumptions, idempotency, retry safety, and partial writes.
- Migration safety, rollback behavior, backfills, online schema changes, and default values.
- Database constraints, uniqueness, foreign keys, validation parity, and impossible states.
- Cache invalidation, stale reads, thundering herds, and queue/database consistency.

### Concurrency And Async

- Shared mutable state, race conditions, deadlocks, lock ordering, and lock scope.
- Unawaited work, blocking calls in async contexts, cancellation safety, and resource cleanup.
- Queue ordering, at-least-once handling, idempotent workers, distributed locks, TTLs, and fencing tokens.

### Reliability And Operations

- Timeouts, backoff, retry storms, circuit breakers, bulkheads, graceful degradation, and overload behavior.
- Resource leaks, unbounded memory growth, file/socket cleanup, connection pool exhaustion.
- Health checks, readiness/liveness semantics, startup/shutdown ordering, and rollback safety.
- Logs, metrics, traces, alerts, runbooks, and whether failures would be diagnosable at 3 AM.

### API And Product Contract

- Backward compatibility, versioning, pagination, sorting, filtering, idempotency, and error response shape.
- Confusing parameter order, stringly typed interfaces, missing validation, and mismatched client/server assumptions.
- Public SDK or CLI behavior, config precedence, and migration notes.

### Performance And Scale

- N+1 queries, missing indexes, unbounded scans, hot-path serialization, excessive allocations, and O(n^2) algorithms.
- Large payload handling, streaming, compression, batching, and pagination.
- Cache size limits, eviction, background compaction, and latency amplification across services.

### Tests

- Coverage for critical paths, edge cases, error paths, permission boundaries, migrations, concurrency, and integrations.
- Assertions that prove behavior rather than "does not crash" checks.
- Mock fidelity, fixture realism, snapshot overuse, flaky time/order/shared-state patterns.

## Worker Prompt Template

```text
Review node: <id> - <name>

Files and context:
- <paths>

Focus:
- <dimensions>

Known dependencies or prior findings:
- <brief notes or none>

Instructions:
1. Read the assigned files and necessary nearby code.
2. Trace reachable source-to-sink or state-transition paths.
3. Check relevant tests before reporting a gap.
4. Report only concrete, reachable issues.
5. Use this exact finding shape:

### [Severity] Short Title
- Location: `path:line`
- Impact:
- Evidence:
- Fix:

If no issues are found, say what was reviewed and name any residual risks.
```

## Synthesis Prompts

After node reviews, ask:

- Which findings share a root cause?
- Which trust boundaries are strong, weak, or unclear?
- Which state transitions can corrupt data under failure or retry?
- Which failures would be invisible or hard to debug in production?
- Which tests would have caught the top findings?
- What is the smallest ordered fix plan by risk reduction?

## Remediation Triage

- `confident fix`: localized, well-understood, low regression risk, testable now.
- `risky fix`: correct direction is likely, but product, migration, compatibility, or architecture tradeoffs need human review.
- `needs human`: missing domain decision, credentials, deployment knowledge, or business rule.
