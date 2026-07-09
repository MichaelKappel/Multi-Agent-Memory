# API Contract Summary

Protected mutation routes support idempotency keys except for free-account setup, which returns a raw key once and does not store raw key material for replay.

Search returns both API-submitted memory and docs-backed durable memory matches from `docs/long-term-memory`.
