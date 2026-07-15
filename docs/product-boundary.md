# Product Boundary

This repository is the public GitHub edition of Multi-Agent Memory: a free
private-intranet MATM hive for one company or organization. It is source
available so people and agents can inspect, run, test, adapt, and improve the
private-network implementation without gaining the right to resell or host a
competing public service.

## Public GitHub Edition

The public edition includes:

- A private-network MATM endpoint runtime.
- Public-safe AI-ready discovery routes.
- One-company workspace setup with a 200 MB free quota.
- Local file, SQLite, and operator-configured MySQL/MariaDB storage backends.
- Agent setup, agent coordination, current messages, meeting rooms, receipts,
  review queue, protected knowledge/wiki routes, and virtual UAIX active memory.
- Demo and verification surfaces that prove the intranet workflows without
  requiring production customer accounts.
- MultiAgentMemory.com as the public companion documentation site for the
  GitHub code, API/data reference, architecture, and handoff model.

The public edition must remain usable without checkout, coupons, subscriptions,
or public hosted customer account setup.

## Reserved Private Commercial Edition

The following belong in a separate private repository or deployment and are not
licensed for resale or public hosted reuse from this public tree:

- MemoryEndpoints.com public hosted service branding, pages, copy, domain
  configuration, deployment scripts, and release operations.
- Authenticated customer account business-model flows.
- Public internet user signup, multi-company hosted tenancy, customer admin,
  support, sales, lead capture, CRM, reseller, affiliate, and enterprise sales
  surfaces.
- Pricing, billing, payment, subscription, coupon, credit-card, overage, invoice,
  and paid-plan enforcement.
- Paid or unlimited hosted storage plans.
- Paid or unlimited NPC memory stores.
- Partner-sponsored commercial setup flows, including Escape.gamesfor.me style
  dogfood sponsorship and public customer-facing unlimited-plan creation.
- Any commercial analytics or operational tooling whose purpose is to sell,
  meter, support, or operate the hosted public MemoryEndpoints.com service.

## Repository Split Rule

MultiAgentMemory.com remains public because it explains the GitHub edition. The
MemoryEndpoints.com public hosted product and the authenticated business-model
implementation move together into the private commercial repository.

Do not add public GitHub code, tests, examples, docs, discovery routes, or UI
copy that teach an unauthenticated caller how to mint a paid, sponsored,
unlimited, or commercial customer workspace. Public examples may describe the
intranet 200 MB free workspace setup and protected MATM operation only.

## Current Transitional State

Some implementation names still use `memoryendpoints` because they predate the
repo split. Renaming modules, environment variables, schemas, and protocol
identifiers should happen deliberately in a migration branch with compatibility
tests. Product-facing copy and public route discovery should use the generic
private-intranet edition identity by default.

Commercial feature extraction is not complete until:

- The private commercial repository exists and is explicitly marked private.
- MemoryEndpoints.com hosted copy, pricing, account, billing, paid NPC-store,
  and sponsored setup code have been moved or reimplemented there.
- The public GitHub route inventory, OpenAPI, `llms.txt`, sitemap, README,
  license, NOTICE, docs, and tests no longer expose paid/sponsored setup.
- Public package and secret scans prove no commercial secrets or customer data
  were copied into the public edition.
