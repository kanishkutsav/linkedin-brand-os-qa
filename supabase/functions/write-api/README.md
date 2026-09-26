# Brand OS write-api (Phase 5 QA)

QA-only target runtime for retry-safe, non-LinkedIn mutations.

Staged operations: create draft, learning thought, approve, edit, reject.

The function preserves the existing Brand OS bearer-token session contract and user/profile ownership checks. It is not deployed to production.

Every mutation that can be retried accepts X-Idempotency-Key. Results are persisted in mutation_requests so browser retries do not repeat the business operation.

AI generation/regeneration remains a durable-job concern. LinkedIn OAuth/publish remains Phase 7.

Production cutover is intentionally deferred until route-by-route parity testing is complete.
