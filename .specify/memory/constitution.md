<!--
Sync Impact Report
==================
Version change: (template / unratified) → 1.0.0
Bump rationale: Initial ratification. The prior file was the stock Spec Kit
scaffold with no project content; this is the first governing version.

Modified principles:
  - [PRINCIPLE_1_NAME] → I. Product-First Architecture
  - [PRINCIPLE_2_NAME] → II. Preserve and Evolve the Existing Foundation
  - [PRINCIPLE_3_NAME] → III. Project-Centric Architecture
  - [PRINCIPLE_4_NAME] → IV. Multi-Tenant by Design
  - [PRINCIPLE_5_NAME] → V. AI-Provider Independence
  (expanded from 5 template slots to 20 ratified principles — see below)

Added sections:
  - Core Principles I–XX (VI. Structured Application Representation,
    VII. Generated Code Is Untrusted, VIII. Security by Default,
    IX. Human Approval for Dangerous Operations, X. Observable and Auditable
    Systems, XI. Testable Generation, XII. Versionability and Reversibility,
    XIII. Production Engineering Discipline, XIV. UX Quality, XV. Evidence
    Over Assumptions, XVI. Incremental Implementation, XVII. Open-Source
    Compliance, XVIII. No Destructive Development, XIX. Operational Isolation,
    XX. Documentation Is Part of the Architecture)
  - Platform Constraints and Security Boundaries
  - Development Workflow and Quality Gates
  - Governance (amendment procedure, versioning policy, compliance review)

Removed sections: none (template placeholders replaced).

Follow-up TODOs: none. RATIFICATION_DATE set to the Phase 0 adoption date.

Templates / dependent artifacts reviewed:
  - .specify/templates/*, .specify/workflows/* — read at runtime; not modified
    here (per command scope guard).
-->

# LG Telecoms App Builder Constitution

LG Telecoms App Builder is a production-grade, multi-tenant SaaS platform for AI-assisted
application development. It is being transformed from the inherited open-source
`screenshot-to-code` project (MIT © 2023 Abi Raja). This constitution governs how that
transformation is designed, built, reviewed, and operated. It supersedes convenience,
habit, and upstream assumptions wherever they conflict.

## Core Principles

### I. Product-First Architecture

LG Telecoms App Builder MUST be designed and built as a production SaaS application-building
platform, not as a screenshot-to-code demo with extra features bolted on. Every design
decision MUST be evaluated against the target: organizations and teams using a hosted,
multi-tenant AI development environment to generate, iterate on, test, version, and deploy
real applications. "It works as a local single-user tool" is never sufficient justification
for a platform-facing capability.

**Rationale:** The inherited codebase is a single-user, no-auth, no-database, keys-in-browser
tool. Treating it as "almost done" would carry single-tenant assumptions into a product where
every cross-cutting concern (identity, tenancy, isolation, billing, auditability) is
load-bearing.

### II. Preserve and Evolve the Existing Foundation

Where the inherited implementation is technically sound, it MUST be evolved incrementally
rather than rewritten. The generation agent loop, provider adapters, canonical tool
definitions, prompt pipeline, cost/usage math, and eval tooling are assets to wrap and
extend. A rewrite of any such subsystem REQUIRES documented evidence that incremental
evolution is infeasible or more costly than replacement, reviewed and approved as an
architectural decision.

**Rationale:** The generation engine is relatively mature and battle-tested by upstream.
Rewrites discard working behavior, hidden constraints, and test coverage; the platform gap
is around the engine, not inside it.

### III. Project-Centric Architecture

The Project MUST be the primary unit of application generation, iteration, versioning,
testing, and deployment. A Project owns its inputs, understanding/analysis/plan artifacts,
application representation, generated code, versions, previews, tests, AI sessions, and
deployments as first-class, server-owned entities. Features MUST attach to a Project rather
than to a transient client session or a global namespace.

**Rationale:** Today the client is the database and "project" has no server-side existence.
Durable collaboration, history, sharing, and deployment are impossible until the Project is a
real, persisted aggregate.

### IV. Multi-Tenant by Design

Organizations, workspaces, users, teams, roles, permissions, usage metering, and tenant
isolation MUST be treated as first-class platform concerns from the first line of platform
code. Every tenant-scoped data path MUST carry and enforce a tenant boundary. Cross-tenant
data exposure is a release-blocking defect. New tables, endpoints, storage keys, and
background jobs MUST state their tenancy model before merge.

**Rationale:** Multi-tenancy is the defining requirement of the product and cannot be
retrofitted safely. Isolation added late leaks data.

### V. AI-Provider Independence

The system MUST NOT be architected around any single AI provider or model. Provider and
model access MUST go through capability-aware abstractions (a model registry with
capabilities and pricing, provider adapters, and capability/cost-based routing). Task-to-model
selection MUST be policy-driven and overridable, not hard-coded into business logic. Adding,
removing, or swapping a provider MUST be a configuration and adapter change, not a
cross-cutting refactor.

**Rationale:** Provider capabilities, pricing, and availability change constantly, and
per-tenant model policy is a product requirement. Single-provider coupling is a strategic and
operational risk.

### VI. Structured Application Representation

Wherever appropriate, a typed Application IR MUST serve as the architectural source of truth
between AI understanding/planning and generated implementation. Versioning, diffing, targeted
regeneration, and repair SHOULD operate on the IR rather than on raw generated text. The IR
MUST be de-risked with timeboxed spikes before any capability is built to depend on it, and
MUST be adopted incrementally (starting with already-supported stacks) rather than
big-bang.

**Rationale:** When the only source of truth is an LLM-generated code blob, reliable
regeneration, scoped repair, stack migration, and diffable versioning are all blocked. A
typed IR makes these tractable — but only if proven before it becomes load-bearing.

### VII. Generated Code Is Untrusted

All generated applications MUST eventually execute only within controlled sandbox boundaries
with enforced CPU, memory, process, wall-clock, filesystem, and network limits. The system
MUST NOT depend on unrestricted or root access to run, preview, test, or build generated
code. Secrets MUST be injected per run and never baked into images or layers. Interim states
(e.g. non-sandboxed preview) MUST be tracked as known risks with a scheduled remediation.

**Rationale:** Generated code is authored by an LLM from untrusted input. Running it with
ambient privileges — as the inherited code does in a non-sandboxed iframe and a
`--no-sandbox` headless browser — is unacceptable for a hosted platform.

### VIII. Security by Default

Secrets management, authentication, authorization, tenant isolation, generated-code
execution, filesystem access, network access, and other dangerous operations MUST each have
an explicit, documented security boundary. The secure configuration MUST be the default;
insecure modes REQUIRE an explicit opt-in, a documented rationale, and a scope limit (e.g.
local development only). "Open by default" (wildcard CORS, unauthenticated internal
endpoints, browser-held provider keys) is prohibited in any shared or hosted deployment.

**Rationale:** The inherited system has no authentication anywhere and treats generated code
as trusted. Security added reactively leaves gaps; it MUST be a design input, not a later
pass.

### IX. Human Approval for Dangerous Operations

Operations that can materially affect infrastructure, production systems, customer data, or
security posture MUST support explicit approval gates. This includes (non-exhaustively)
deployments to production, outbound network access from sandboxes, package installation from
non-allowlisted registries, destructive data operations, membership/role changes, and
provider-key access. Approval gates MUST record who approved what, when.

**Rationale:** Automated agents and pipelines will increasingly drive real infrastructure
actions. A human decision point on irreversible or high-blast-radius operations is a
non-negotiable safety control.

### X. Observable and Auditable Systems

Important application, AI, infrastructure, and administrative actions MUST eventually emit
structured logs with correlation/trace identifiers, and security-relevant actions MUST be
recorded in an append-only audit history. New services and endpoints MUST log in structured
form (no `print`-style logging in platform code going forward). Traceability across
API → queue → worker → provider calls is the target and MUST be designed for, not
precluded.

**Rationale:** A multi-tenant platform that touches money, infrastructure, and customer code
cannot be operated, debugged, or trusted without structured observability and a tamper-evident
audit trail.

### XI. Testable Generation

Generated applications MUST eventually pass automated functional and visual validation.
Browser automation (Playwright) SHOULD drive smoke and interaction checks derived from the
build plan, and visual QA SHOULD compare output against the target design and feed scoped
repair loops with bounded budgets. Repair loops MUST have convergence controls (max
iterations, quality thresholds, human override).

**Rationale:** Unvalidated generation output is a guess. Closing the generate → preview →
compare → diagnose → repair loop is what makes generation a reliable product capability
rather than a novelty.

### XII. Versionability and Reversibility

Generation runs, edits, and major Project changes MUST support checkpoints, snapshots,
history, and rollback. A user or operator MUST be able to return a Project to a prior known
state. Version history MUST be durable server-side, not client-only.

**Rationale:** The inherited client-side `commits` map is lost on refresh. Users iterating
with an AI need a safety net; without reversibility, every generation is a risk.

### XIII. Production Engineering Discipline

Platform code MUST use typed interfaces, automated tests, continuous integration,
reproducible environments (pinned language/runtime/dependency versions), disciplined
dependency management, and documented architectural decisions. Every change MUST leave the
application runnable with a green test suite and type checks. New warnings in changed files
are not acceptable.

**Rationale:** The inherited project has no CI, an untested interpreter version, and unpinned
foot-guns. A production platform requires the checks that make change safe and repeatable.

### XIV. UX Quality

The product MUST present a professional AI development environment, not a form-based
generator. Accessibility, responsive design, visual consistency, and interaction quality
are first-class requirements, evaluated in review alongside correctness. Regressions in these
dimensions are defects.

**Rationale:** The product competes as a development environment. UX quality is a core
attribute of the offering, not decoration.

### XV. Evidence Over Assumptions

Architectural decisions MUST be grounded in the actual state of this repository and
validated through tests, measurements, and documented evidence. Claims about current
behavior MUST cite code. Proposed decisions MUST record rationale, alternatives considered,
trade-offs, and migration implications. Assumptions carried forward from upstream
documentation MUST be verified against current code before they inform a decision.

**Rationale:** Upstream design docs in this repo are already partly stale. Decisions built on
unverified assumptions compound into expensive mistakes.

### XVI. Incremental Implementation

Work MUST proceed in controlled phases with explicit entry and exit gates. Future platform
capabilities MUST NOT be implemented ahead of their phase or before their prerequisites
(especially security prerequisites) are in place. Each increment MUST ship something usable
and leave the system in a runnable, tested state.

**Rationale:** The gap between the inherited tool and the target platform is large.
Sequencing with gates keeps the system shippable throughout and prevents building on
unproven foundations.

### XVII. Open-Source Compliance

Upstream MIT licensing, copyright notices, and attribution requirements MUST be preserved
while the product is rebranded and transformed into LG Telecoms App Builder. The `LICENSE`
file, upstream author attribution, and third-party license obligations MUST remain intact
and MUST be reviewed whenever dependencies or distribution change.

**Rationale:** The product is derived from MIT-licensed work. Honoring the license is both a
legal obligation and a matter of integrity.

### XVIII. No Destructive Development

Existing functionality MUST NOT be deleted or overwritten without documented evidence
justifying the change, a migration strategy, and tests covering the transition. Removing a
capability REQUIRES the same rigor as adding one.

**Rationale:** The inherited engine encodes hard-won behavior and constraints. Destructive
edits without evidence and migration paths cause silent regressions.

### XIX. Operational Isolation

Development and automation for this project MUST NOT interfere with unrelated processes,
repositories, services, or developer environments. Work stays within this repository and its
declared dev stack. Shared or external systems are touched only with explicit authorization.

**Rationale:** The platform's own principle of tenant isolation applies to how it is built.
Spillover into unrelated systems is a reliability and trust failure.

### XX. Documentation Is Part of the Architecture

Major decisions, public and internal interfaces, workflows, security boundaries, and
operational procedures MUST be documented as part of the work that introduces them, not
afterward. A change that alters architecture, a contract, a security boundary, or an
operational procedure is incomplete until its documentation is updated.

**Rationale:** A platform built by a team and operated in production is only as maintainable
as its documentation. Undocumented decisions become tribal knowledge and then lost knowledge.

## Platform Constraints and Security Boundaries

- **Tenancy:** `Organization → Workspace → Project` is the canonical hierarchy. Every
  tenant-scoped table, object-storage key, cache entry, queue job, and endpoint MUST declare
  and enforce its tenant boundary. Cross-tenant leakage blocks release.
- **Identity and secrets:** Provider API keys and other secrets MUST live server-side in a
  secrets manager, never in the browser or in client-shipped config, in any shared or hosted
  deployment. Authentication is required for all non-public endpoints.
- **Generated-code execution:** Preview, QA, test, and build of generated code MUST target a
  resource-capped sandbox with no network egress by default. The API process MUST NOT execute
  generated code. Known interim gaps MUST be tracked with remediation owners.
- **Network boundaries:** Outbound calls from the platform and from sandboxes MUST be
  allowlisted. SSRF protections on user-influenced fetches MUST be preserved and extended, not
  removed.
- **Cost controls:** Per-run spend ceilings MUST be preserved and generalized into per-tenant
  and per-project budgets with soft/hard enforcement.
- **Reproducibility:** Language runtime, package manager, and dependency versions MUST be
  pinned and documented; dev, CI, and production MUST agree on them.
- **Licensing:** The upstream MIT license and attribution MUST remain intact through
  rebranding and redistribution.

## Development Workflow and Quality Gates

- **Baseline checks (every change):** backend `pytest` and `pyright` (no new warnings in
  changed files); frontend `pnpm lint` and tests. Changes touching both run both. A change
  that leaves the app non-runnable or the suite red is not mergeable.
- **Continuous integration:** CI MUST run the baseline checks on every pull request. New work
  MUST NOT depend on checks that CI does not enforce.
- **Architectural decisions:** Any change to architecture, a cross-cutting contract, a
  security boundary, or an operational procedure MUST be recorded in the project's decision
  and architecture docs as part of the same change.
- **Evidence in review:** Claims about current behavior cite code; proposed decisions record
  rationale, alternatives, trade-offs, and migration implications.
- **Phase gates:** Each phase has explicit entry prerequisites and exit criteria. Security
  prerequisites (sandboxing, secrets, auth, isolation) land before the capabilities that make
  them urgent.
- **Destructive change:** Deleting or replacing existing functionality REQUIRES evidence, a
  migration plan, and transition tests, reviewed as an architectural decision.
- **Scope discipline:** Feature implementation is out of scope for governance and planning
  commands; product code changes happen only through the specify → plan → tasks → implement
  flow.

## Governance

This constitution supersedes other practices and conventions where they conflict. All
reviews and pull requests MUST verify compliance with these principles; a reviewer MUST block
a change that violates a principle unless a documented, time-bound exception is recorded in
the change and its supporting docs.

**Amendment procedure:** Amendments are proposed as a change to this file with a written
rationale. An amendment REQUIRES review and approval by the project's maintainers, an
assessment of impact on dependent templates and workflows, and a migration note when the
change affects existing work. On merge, the Sync Impact Report at the top of this file MUST
be updated.

**Versioning policy (semantic):**
- **MAJOR** — backward-incompatible governance changes: removing or redefining a principle,
  or removing a section, in a way that changes what compliance requires.
- **MINOR** — adding a new principle or section, or materially expanding guidance.
- **PATCH** — clarifications, wording, and non-semantic refinements.

**Compliance review:** Adherence is checked continuously in code review and revisited at each
phase gate. Recurring violations of a principle are a signal to strengthen tooling or
enforcement, not to weaken the principle. Unavoidable interim deviations MUST be documented
as known risks with an owner and a remediation plan.

**Version**: 1.0.0 | **Ratified**: 2026-09-02 | **Last Amended**: 2026-09-02
