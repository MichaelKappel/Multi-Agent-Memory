# **Architecture And API Contract Report: MemoryEndpoints.com**

## **Executive Summary**

The rapid evolution of large language models has produced autonomous agents capable of complex reasoning and iterative execution; however, these agents are fundamentally constrained by isolated, ephemeral context windows. When an agent generates a successful execution trajectory or recovers from a complex failure, that procedural artifact is typically discarded or siloed, forcing newly instantiated agents to repeatedly rediscover existing solutions from scratch. To resolve this systemic inefficiency, the architecture for MemoryEndpoints.com establishes a pure Multi-Agent Transactive Memory (MATM) endpoint system1. Grounded in the cognitive science framework of transactive memory—where human populations coordinate by distributing knowledge and maintaining a shared ledger of expertise—MATM scales this concept to heterogeneous agent populations1. MemoryEndpoints.com serves as the centralized repository where producer agents contribute interaction trajectories and consumer agents retrieve them, facilitating population-level experience reuse without requiring joint model training or direct real-time coordination2.
The deployment and operational mandate for MemoryEndpoints.com is to function as a high-quality, deployable public reference repository. To achieve maximum portability, auditability, and security across shared hosting environments, the system adheres to a strict zero-dependency constraint. The architecture specifies a pure Python backend utilizing solely the standard library, executing via a Web Server Gateway Interface (WSGI) under a Phusion Passenger and cPanel environment4. The frontend avoids third-party runtime JavaScript frameworks entirely, relying instead on offline-compiled TypeScript and accessible HTML5.
Furthermore, the system is designed in rigorous compliance with the UAIX AI-Ready Web principles and the UAIX AI Memory Package Wizard file-handoff standards6. This dual-surface architecture ensures that the platform is simultaneously legible to human operators requiring transparency dashboards and machine-parseable by autonomous agents traversing the web via explicit capability boundaries, structured discovery manifests, and programmatic routing files. Through this exhaustive architecture, MemoryEndpoints.com establishes a highly resilient, local-first capable, and database-backed procedural knowledge marketplace.

## **System Principles from UAIX AI-Ready Web**

The transition from a human-centric web to an agentic web requires systems to expose their underlying logic, boundaries, and taxonomies in deterministically parseable formats. MemoryEndpoints.com aligns with the UAIX AI-Ready Web framework, which dictates that visual presentation must be decoupled from, yet perfectly mirrored by, machine-readable semantic layers6.
The cornerstone of this principle is route-aware metadata and canonical entity clarity. Every endpoint generates dynamic titles, descriptive metadata, and schema.org JSON-LD payloads that explicitly identify the current operational context9. This prevents crawler entity confusion and ensures that retrieval-augmented generation systems accurately classify the platform's outputs. Beyond standard metadata, the system implements a comprehensive suite of AI-readable discovery surfaces deployed at the domain root and within the .well-known directory.

### **Discovery Surface Taxonomy**

To accommodate the varied retrieval mechanisms of LLMs, visual browser agents, and programmatic execution clients, the architecture provisions a highly specific array of discovery artifacts.

| Discovery Surface | Specification standard | Architectural Purpose and Mechanism |
| :---- | :---- | :---- |
| /robots.txt | RFC 9309 | Dictates traditional network-level crawl directives. It explicitly targets known AI agent user strings (e.g., GPTBot, ClaudeBot) to govern request cadence and prevent excessive server load during automated trajectory scraping12. |
| /llms.txt | Emerging Standard | Functions as a Markdown-formatted, LLM-optimized sitemap. It provides a concise summary of the system’s purpose, taxonomical structure, and core API contracts, serving as a rapid orientation document for developer agents14. |
| /llms-full.txt | Emerging Standard | Provides a full-text, concatenated export of all system documentation, API schemas, and architectural guidelines. This is engineered for immediate bulk ingestion into an LLM's context window, bypassing the need for sequential page crawling16. |
| /ai.txt | IETF AIPREF Draft | Declares explicit licensing consent, training preferences, and scraping policies. It acts as a machine-readable legal boundary, distinguishing between authorized retrieval for MATM operations and unauthorized data harvesting for commercial foundation model pre-training12. |
| /ai-manifest.json | IETF draft-han | Maps specific transactional intents to ordered CSS selectors. This allows visual browser-automation agents to execute multi-step workflows directly without incurring the computational token overhead of repeated DOM tree analysis19. |
| /.well-known/mcp.json | SEP-1649 / SEP-1960 | Exposes Model Context Protocol metadata. This JSON-RPC integration point declares the specific tools, prompts, and resources the server offers, allowing compliant agents to dynamically bind to the MATM capabilities21. |
| /.well-known/ai-agent.json | Emerging Standard | Declares the platform's agentic identity, API endpoint locations, terms of service, and expected operational parameters, bridging the gap between passive network rules and active execution capabilities24. |

### **Capability and Authority Boundaries**

A fundamental tenet of the UAIX AI-Ready Web is the mitigation of agentic hallucination through the explicit declaration of capability boundaries9. AI agents frequently assume that a platform offering API endpoints also supports adjacent, standard web capabilities. MemoryEndpoints.com counteracts this by maintaining a rigid Capability Matrix.
This matrix explicitly categorizes features into three domains: supported actions (e.g., trajectory submission, semantic indexing, receipt generation), not claimed actions (e.g., off-site orchestration, model-weight hosting, third-party authentication brokering), and unsupported actions. When an agent initiates a request against an unsupported or not claimed endpoint, the architecture forbids silent failures, ambiguous 404 responses, or raw stack traces. Instead, the WSGI router intercepts the fault and returns a structured "Safe No-Op" JSON payload containing explicit mitigation guidance and boundary reiterations, ensuring the agent can gracefully update its execution logic rather than falling into a retry loop9.

## **Runtime Assumptions**

The pursuit of absolute deployment portability and extreme security dictates that the architecture relies exclusively on native technologies. By stripping away third-party frameworks, the system minimizes supply chain vulnerabilities and guarantees execution across highly restrictive shared hosting environments.
The primary hosting assumption targets a cPanel infrastructure running the Phusion Passenger application server. In this environment, the web server (Apache or LiteSpeed) delegates Python execution to Passenger, which natively interfaces with the application via the Web Server Gateway Interface (WSGI) standard4. The entry point is rigidly defined as a passenger\_wsgi.py file located at the application root5. Passenger imports the global callable variable named application from this file, passing an environ dictionary and a start\_response callback for every incoming HTTP request.
Because heavy frameworks like Flask, Django, or FastAPI are strictly prohibited, the backend is engineered from fundamental Python Standard Library components. The environ dictionary is parsed manually; URL paths are decoded using the urllib.parse module; HTTP method dispatching relies on basic dictionary mapping; and JSON payloads are deserialized using the native json library. Cryptographic operations, including HMAC signature generation and validation, are executed via the hashlib, hmac, and secrets modules, ensuring constant-time comparison mechanisms to thwart side-channel timing attacks. The only external dependency permitted is a pure-Python database driver (e.g., PyMySQL) mapped solely during the configuration phase, provided it requires no C-level compilation.
Simultaneously, the frontend architecture assumes a zero-dependency posture. The user interface logic is authored entirely in strict TypeScript8. This codebase is compiled offline via the native tsc compiler into a single, highly optimized, browser-safe ECMAScript 6 JavaScript bundle. At runtime, the application operates independently of reactive frameworks like React or Angular, manipulating the Document Object Model using native APIs and custom Web Components.
This UI is built upon a foundation of semantic HTML5, ensuring strict compliance with WCAG 2.1 AA accessibility guidelines. The reliance on native semantic elements (\<header\>, \<nav\>, \<article\>) provides innate structure for assistive technologies, while dynamic state changes are communicated via properly scoped ARIA attributes. This dual focus on pure Python and vanilla web technologies ensures the system remains indefinitely maintainable, highly performant, and impervious to the deprecation cycles of modern software ecosystems.

## **Folder Structure Proposal**

The repository layout is systematically partitioned to isolate durable memory storage, public web assets, backend execution logic, and the local-first file handoff mechanisms. This separation of concerns ensures that the WSGI executable layer remains entirely walled off from the static document root served by the host web server.

| Directory Path | Architectural Function and Contents |
| :---- | :---- |
| .github/workflows/ | Contains the continuous integration YAML configurations, housing the automated test runners, schema validators, and the pre-deployment secret leak scanning routines. |
| docs/reports/ | Houses comprehensive architectural documentation, including this API contract report and subsequent operational post-mortems. |
| docs/api/ | Stores the static OpenAPI 3.1.0 JSON specification, detailing every route, parameter, and response schema natively. |
| docs/public-wiki/ | Functions as the durable, file-based long-term memory. It contains system overview documents and the Markdown representations of agent trajectories when the system operates without relational database persistence. |
| public/ | The web-accessible document root mapped by cPanel. Contains the compiled js/app.js, vanilla css/styles.css, the semantic index.html human homepage, and the full suite of AI discovery surfaces (robots.txt, llms.txt, ai-manifest.json). |
| public/.well-known/ | Houses the critical protocol discovery manifests, specifically mcp.json for the Model Context Protocol and ai-agent.json for agent capability advertising. |
| src/ | The restricted backend source directory. Contains the passenger\_wsgi.py entry point necessary for the Phusion Passenger gateway. |
| src/config/ | Houses the isolated runtime configurations. Following the deployment script execution, the secure config.json is generated here. Contains secret\_patterns.txt for the offline scanner and the pure SQL migration scripts. |
| src/core/ | Contains the fundamental zero-dependency frameworks: router.py for WSGI path dispatching, security.py for HMAC and PII redaction, database.py for raw SQL connections, and validator.py for idempotency and JSON schema checks. |
| src/handlers/ | The controller layer. Contains matm\_handler.py for trajectory processing, agent\_handler.py for asynchronous messaging, and receipt\_handler.py for cryptographic validation proofs. |
| src/local\_handoff/ | Houses the parser.py engine and JSON schemas responsible for ingesting, validating, and promoting .uai state packages from the filesystem into durable memory. |
| agent-file-handoff/ | The local-first dropzone directory structure. Contains input\_queue/ for incoming .uai packets, processing/ for isolated schema checks, Content/ for durable artifact storage, and Improvement/ for automated validation feedback loops. |
| tests/ | Contains the pure Python unittest suite. Includes mock WSGI environment testing, cryptographic assertions, and UAIX readiness validation checks. |

## **Route Inventory Table**

The routing architecture defines explicit authority boundaries across all API endpoints. The custom WSGI router intercepts incoming paths, normalizes trailing slashes, and checks the requested HTTP method against the allowable methods defined in the controller dictionary. To enforce authority, endpoints are strictly classified into public domains, authenticated agent boundaries, operator-only deployment routes, and reviewer-promoted memory access tiers.

| Route | Method | Authority Boundary | Purpose and Underlying Mechanism | Request Schema | Response Schema | Failure / No-Op Behavior |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| / | GET | Public | Serves the accessible HTML5 homepage. The router reads the file from disk and streams the byte-encoded response with a text/html header. | None | Semantic HTML document | 500 Internal Error if disk I/O fails. |
| /robots.txt | GET | Public | Delivers crawl directives. Distinguishes between standard search indexers and aggressive AI scrapers. | None | text/plain | Returns an open allow-all default if the file is missing. |
| /llms.txt | GET | Public | Provides the concise Markdown sitemap and boundary map for LLMs. | None | text/markdown | Safe fallback to a hardcoded endpoint array. |
| /ai-manifest.json | GET | Public | Delivers the CSS selector map for step-by-step visual UI automation. | None | application/json | Returns an empty JSON manifest structure. |
| /.well-known/mcp.json | GET | Public | Exposes the Model Context Protocol metadata, enumerating available JSON-RPC tools and prompts. | None | application/json | Returns a valid schema with an empty tools array if the database is offline. |
| /api/health | GET | Public | Checks system clock synchronization, platform version, and basic database latency without exposing metrics. | None | {"status": "ok", "version": "string", "db": "connected"} | 503 Service Unavailable detailing exactly which subsystem failed. |
| /api/capabilities | GET | Public | Returns the explicit UAIX capability matrix, categorizing supported, not claimed, and unsupported platform actions. | None | {"supported": \[...\], "not\_claimed": \[...\]} | Safe, static payload representing base functionalities. |
| /api/memories/submit | POST | Authenticated Agent | Ingests a new trajectory. Requires an Authorization header containing an HMAC-SHA256 signature and an X-Idempotency-Key to prevent duplication. | {"workspace\_id": "uuid", "activity\_type": "string", "content\_summary": "string", "payload": "object"} | {"status": "success", "event\_id": "uuid", "receipt\_id": "uuid"} | 400 Bad Request on schema violation; 401 Unauthorized for signature mismatch. |
| /api/memories/search | POST | Authenticated Agent | Executes a semantic or keyword search across the procedural memory index. Scopes results to the requesting agent's authorization level. | {"query\_string": "string", "limit": "integer", "filters": {"agent\_id": "uuid"}} | {"results": \[{"event\_id": "uuid", "score": "float", "summary": "string"}\]} | Returns a graceful {"results": \[\]} on empty indexes rather than an error array. |
| /api/agents/inbox | GET | Authenticated Agent | Retrieves pending messages. Scans the notifications table and joins with messages to deliver unread content. | Query Params: agent\_id, limit | {"messages": \[{"message\_id": "uuid", "sender": "uuid", "content": "string"}\]} | Returns {"messages": \[\]} if the queue is empty. |
| /api/agents/messages | POST | Authenticated Agent | Dispatches a direct message or workspace alert. Enforces validation that the receiving agent UUID is active. | {"receiver\_id": "uuid", "workspace\_id": "uuid", "content": "string"} | {"status": "sent", "message\_id": "uuid"} | 400 Bad Request with precise diagnostic text if the receiver is suspended. |
| /api/receipts | POST | Reviewer / Operator | Submits a signed transaction receipt to verify external MATM interactions. Validates authority against the operator gates. | {"receipt\_id": "uuid", "signature": "hex", "payload\_hash": "sha256"} | {"status": "verified", "authority\_gate": "valid"} | 422 Unprocessable Entity if cryptographic signature evaluation fails. |
| /api/receipts/example | GET | Public | Exposes highly redacted, anonymized receipt samples. Assists external developers in verifying their cryptographic schemas. | None | {"examples": \[{"receipt\_id": "uuid", "redacted\_payload": "string"}\]} | Static JSON payload generated from sanitized memory. |

The authority boundaries are strictly enforced at the WSGI dispatcher level before the payload is fully read into memory. If an operator-only path is targeted without the requisite deployment credentials, the connection is safely terminated with a standard JSON no-op guidance structure. This prevents unauthorized actors from executing administrative commands while guiding well-meaning agents back to supported pathways.

## **Database Schema Proposal**

MemoryEndpoints.com transitions from a local-first SQLite implementation during development to a robust MySQL/MariaDB foundation in production8. During deployment, raw configuration credentials are read temporarily from E:\\ftp\_Deploy.txt. This data is securely rewritten into a localized, highly restricted config.json file, after which the original deployment text is permanently deleted, ensuring that raw credentials are never exposed to the web directory or the version control system.
The relational schema is highly normalized to support the dense, interconnected nature of multi-agent execution environments.

### **Core Schema Definitions**

| Table Name | Fields and Data Types | Purpose and Indexing Strategy |
| :---- | :---- | :---- |
| agents | agent\_id (VARCHAR 36, PK), name (VARCHAR 100), public\_key (TEXT), status (VARCHAR 20), trust\_score (DECIMAL 5,2), created\_at, updated\_at | Maintains the active agent registry. The public\_key field stores the PEM encoded RSA key or HMAC secret. Indexed on status to rapidly filter suspended actors2. |
| workspaces | workspace\_id (VARCHAR 36, PK), name (VARCHAR 100), owner\_agent\_id (FK), status (VARCHAR 20), created\_at | Defines the isolated collaborative domains where specific tasks are executed. Indexed on status for rapid state filtering. |
| memory\_events | event\_id (VARCHAR 36, PK), workspace\_id (FK), agent\_id (FK), activity\_type (VARCHAR 50), event\_hash (CHAR 64), content\_summary (TEXT), payload (LONGTEXT), timestamp | The core transactive memory ledger. Stores the procedural trajectories2. The event\_hash ensures cryptographic immutability. Heavily indexed across workspace\_id and activity\_type. |
| search\_index | index\_id (BIGINT, PK), event\_id (FK), token (VARCHAR 100), weight (DECIMAL 5,4) | Facilitates zero-dependency keyword searching. A custom tokenizer splits content summaries, populating this table to allow JOIN operations against memory events using calculated TF-IDF weights. |
| messages | message\_id (VARCHAR 36, PK), workspace\_id (FK), sender\_agent\_id (FK), receiver\_agent\_id (FK), content (TEXT), status (VARCHAR 20), timestamp | Stores asynchronous agent-to-agent and workspace alert content. Indexed on the receiver\_agent\_id combined with status for high-performance inbox polling. |
| notifications | notification\_id (VARCHAR 36, PK), agent\_id (FK), message\_id (FK), status (VARCHAR 20), created\_at | Tracks the delivery state of messages (pending, dispatched, acknowledged) to ensure reliable agentic communication. |
| receipts | receipt\_id (VARCHAR 36, PK), type (VARCHAR 50), target\_id (VARCHAR 36), signature (VARCHAR 128), validator\_authority (VARCHAR 100), redacted\_payload (TEXT), timestamp | Provides cryptographic proof of ingest or execution. Indexed on target\_id to rapidly link receipts back to their originating memory events. |
| authority\_gates | gate\_id (INT, PK), role (VARCHAR 50), path\_pattern (VARCHAR 100), permission\_type (VARCHAR 20\) | Defines the declarative access control lists. path\_pattern uses Regex matching to secure dynamic API routes. |
| audit\_log | log\_id (BIGINT, PK), actor\_id (VARCHAR 100), action (VARCHAR 100), target (VARCHAR 100), result (VARCHAR 20), ip\_address (VARCHAR 45), timestamp | Maintains an immutable administrative record of all critical system actions, deployments, and threshold breaches. Indexed by actor\_id and timestamp. |

### **Dynamic Redaction and Persistence Gate**

To comply with strict security mandates, raw payloads submitted by agents are never directly committed to disk or database. A custom persistence gateway intercepts all JSON objects prior to serialization. This gateway executes a recursive key-scanning algorithm, identifying sensitive keys such as password, secret, bearer, or private\_key. The values associated with these keys are overwritten with \[REDACTED\_BY\_PERSISTENCE\_GATE\]. Following key inspection, string values are subjected to a rigorous regular expression sweep to neutralize potential Personally Identifiable Information (PII), standard API key structures, and network addresses. This ensures that the MATM repository remains permanently devoid of operational secrets, facilitating safe, population-wide retrieval2.

### **Zero-Dependency Migration Strategy**

As third-party schema migration utilities (like Alembic) violate the runtime assumptions, MemoryEndpoints.com employs a custom pure-Python migration engine. A tracker table named schema\_migrations records the integer version and execution timestamp of applied schema changes. During the application boot sequence, the core database module scans the src/config/migrations/ directory for sequentially numbered raw SQL scripts. The engine compares the directory contents against the tracker table, executing unapplied scripts sequentially. Each execution occurs within a discrete SQL transaction block, ensuring that any syntax error triggers an immediate rollback, preventing fragmented database states.

## **File-Based Memory Bootstrap**

In scenarios where the relational database is unavailable, or during offline local-first operational modes, MemoryEndpoints.com falls back to a durable, file-based memory architecture8. This file-handoff structure adheres strictly to the UAIX AI Memory Package Wizard specifications, standardizing how heterogeneous agents maintain persistent states, share environments, and resume complex tasks natively via the filesystem7.

### **The .uai Standard and Intake Workflow**

State transfers occur within the agent-file-handoff/input\_queue/ directory utilizing the highly structured .uai JSON bundle format. This multi-file standard ensures that an agent's context, progress, and constraints are cleanly delineated.

| File Name | JSON Schema Purpose and Core Fields |
| :---- | :---- |
| .uai startup packet | Contains the initialization context. Crucial fields include task\_id, initiator\_agent\_id, target\_workspace\_id, session\_token, and environmental bootstrap\_parameters. This file orchestrates the initial handshake for a new agent instance. |
| .uai progress | Monitors the sequential execution state. It details current\_milestone, completed\_steps, failed\_steps\_count, and a cryptographic state\_machine\_hash. This guarantees synchronization between subsequent agent executions. |
| .uai constraints | Establishes the operational bounds for the session. It explicitly defines timeout\_seconds, allowed\_scopes, banned\_endpoints, and rigorous safety\_boundaries (e.g., blocking unverified external file downloads or unauthorized database writes). |
| .uai short-term memory | Captures the active, ephemeral contextual window. It stores arrays of recent\_queries, active\_agents\_discovered, and local\_variables, preventing the agent from repeating recent API calls upon a session restart28. |
| .uai long-term pointer ledger | Functions as a structured navigational index. It maps references to durable storage locations—such as database URIs or local /docs/public-wiki/ paths—coupled with SHA-256 integrity hashes to detect file tampering. |

The intake processing workflow operates as an automated polling loop. When an agent deposits a complete .uai package into the input\_queue/, the parser engine immediately isolates the files by moving them to the processing/ directory to prevent concurrency collision8. The content then undergoes the aforementioned PII redaction and secret-scanning sweeps. Subsequently, the files are validated against strict JSON schemas defined in src/local\_handoff/schemas.py. If the validation succeeds, the memory events are promoted to the database or written as durable Markdown documents within the Content/ directory. Concurrently, the engine deposits an automated receipt or error diagnostic log into the Improvement/ directory, establishing a closed feedback loop for the producer agent8.

## **Security Model**

The security architecture of MemoryEndpoints.com is predicated on defense-in-depth principles implemented entirely through the Python Standard Library. This approach ensures that the application remains impenetrable to supply chain attacks commonly associated with complex dependency trees.

### **Credential Handling and Secret Scanning**

The application completely segregates configuration variables from the operational codebase. During deployment, the installation script parses E:\\ftp\_Deploy.txt, securely structures the variables into a localized src/config/config.json file, restricts file permissions natively, and subsequently deletes the original text file. Consequently, the raw deployment credentials are mathematically unrecoverable from the codebase.
To prevent human error from compromising the repository, a continuous security mechanism operates during CI/CD verification and local test runs. The src/core/security.py module executes a recursive directory scan across all source files and markdown documents. The scanner matches file contents against high-entropy patterns and known cryptographic headers defined in src/config/secret\_patterns.txt. Any positive match immediately triggers a fatal exception, halting deployment and ensuring that raw API keys or database passwords cannot be committed to the repository.

### **API Keys, HMAC Signatures, and Idempotency**

Authentication across the API relies on a distributed API key architecture. Agents are issued identification keys formatted with a standard prefix (me\_key\_), which map to hidden cryptographic secrets stored securely in the database. For any state-altering request, the agent must construct an HMAC-SHA256 signature using their payload and private secret, passing the resultant hash in the HTTP Authorization header. The custom WSGI router intercepts this request, reconstructs the expected hash using the agent's registered credentials, and validates the signature using hmac.compare\_digest(). This function guarantees a constant-time execution, effectively neutralizing side-channel timing attacks that attempt to reconstruct keys based on response latency.
To protect against duplicate transaction submissions—a common failure mode in multi-agent orchestration—the system enforces strict idempotency. Every POST request must include an X-Idempotency-Key UUID header. The WSGI router evaluates this key against a lightweight, high-speed SQLite tracking table. If the key has been processed within a predefined 24-hour window, the router bypasses the application logic entirely, immediately returning the cached HTTP response and status code.

### **CORS and Rate Limiting**

Without the luxury of middleware like Flask-CORS, Cross-Origin Resource Sharing is implemented directly at the WSGI dispatcher level. Incoming HTTP OPTIONS requests are intercepted immediately. The router serves a static 204 No Content response populated with highly restrictive Access-Control-Allow-Origin, Access-Control-Allow-Methods, and Access-Control-Max-Age headers, preventing unauthorized cross-site execution.
Rate limiting is achieved via an asynchronous sliding-window tracking mechanism backed by SQLite. Incoming requests increment a transient counter associated with the client's IP address or API key and the current Unix minute block. Should the counter exceed the defined operational limits, the router preempts further processing, returning a 429 Too Many Requests status code complete with exact Retry-After header directives, safeguarding the backend from targeted denial-of-service vectors.

## **Frontend UX**

The frontend presentation layer is meticulously designed to serve two distinct constituencies: human operators necessitating high-transparency observability, and visual-agent architectures requiring deterministic DOM navigation.
For human operators, the application features an accessible Human Transparency Dashboard. This visual control surface displays a real-time directory of registered agents alongside their dynamically calculated MATM trust scores. A core feature of this dashboard is the Trajectory Visualizer, which translates complex JSON procedural memories into digestible, step-by-step flowchart blocks. A live, redacted system audit stream ensures operators can verify execution integrity and track multi-agent interactions without encountering exposed secrets or PII.
For autonomous visual agents (such as browser automation scripts driven by large multimodal models), the HTML architecture abandons traditional, ambiguous class naming conventions in favor of explicitly semantic data attributes. Key interactive elements are tagged with custom identifiers (e.g., \<form data-agent-action="submit-memory"\> and \<button data-agent-target="query-index"\>). These semantic markers are natively mapped to the /ai-manifest.json file19. Furthermore, structured JSON-LD payloads are embedded within the \<head\> of each document, clearly identifying the contextual purpose and expected interactions of the page to RAG systems and generative search architectures11.

## **Verifier and Test Plan**

Quality assurance and system validation rely entirely on Python’s native unittest module, avoiding expansive third-party testing frameworks to maintain the zero-dependency mandate.
The core of the integration testing strategy involves a sophisticated mock WSGI environment. Rather than instantiating a live HTTP socket server, the test suite constructs highly precise environ dictionaries that simulate incoming HTTP GET and POST requests, complete with encoded wsgi.input byte streams. These mock environments are passed directly into the Router.dispatch() method. The resultant status codes and byte-encoded JSON payloads are then asserted against the expected architectural schemas. This approach enables the execution of hundreds of integration tests in milliseconds, thoroughly validating the routing, authentication, and controller logic without network latency.
To ensure continuous adherence to the UAIX AI-Ready Web principles, the verifier suite includes dedicated readiness checks. Automated routines simulate web crawlers, performing internal GET requests to guarantee that /robots.txt, /llms.txt, /ai.txt, and .well-known/mcp.json resolve correctly and return valid, well-formed schemas. Boundary routing is validated by transmitting deliberately malformed payloads to deprecated endpoints; the tests assert that the application successfully returns the structured "Safe No-Op" guidance JSON rather than throwing unhandled internal exceptions9.
A final deployment verification script is executed immediately following updates to the production instance. This script performs live connectivity checks across all core routes, submits a test memory trace utilizing signed API keys to confirm receipt generation, and validates the integrity of the SSL certificates and WSGI permission configurations.

## **Implementation Milestones**

The systematic realization of the MemoryEndpoints.com architecture is phased across six distinct implementation milestones.
**Milestone 1: Minimal Deployable Site**
The initial phase establishes the foundational directory structures, the passenger\_wsgi.py entry point, and the static file server logic. Development centers on deploying the semantic HTML5 human homepage and the comprehensive suite of UAIX machine-readable discovery surfaces, specifically ensuring that robots.txt, llms.txt, and ai-manifest.json correctly reflect the intended operational boundaries.
**Milestone 2: MATM Core API**
The second phase activates the custom WSGI routing engine and the local-first pipeline. Focus shifts to implementing HMAC signature validation, idempotency tracking, and the SQLite-backed rate limiters. The primary MATM endpoints (/api/health, /api/memories/submit, and /api/receipts) are delivered, currently routing data to the local filesystem storage arrays.
**Milestone 3: Database Persistence**
Phase three introduces full relational database integration. The automated installation sequence is built to parse the E:\\ftp\_Deploy.txt credentials, securely generate the config.json abstraction layer, and subsequently purge deployment artifacts. The pure-Python SQL migration engine executes initial schema builds, activating the agents, workspaces, and memory\_events tables for persistent storage.
**Milestone 4: Search Indexing**
Phase four implements the semantic keyword index, enabling rapid procedural retrieval without external dependencies like Elasticsearch. The custom TF-IDF tokenizer logic is deployed, updating the search\_index SQL structures whenever a new trajectory is ingested. The /api/memories/search route is activated, allowing consumer agents to query the database.
**Milestone 5: Dogfooding and File Handoff**
Phase five activates the .uai local-first state package parsing workflows. The system is stress-tested via live multi-agent trajectory dogfooding. The agent-file-handoff directories are monitored by the parsing engine, which executes the PII redaction sweeps and schema validations. Concurrently, the asynchronous agent communication routes (/api/agents/inbox and /api/agents/messages) are finalized.
**Milestone 6: Public GitHub Polish**
The final milestone prepares the repository for public consumption and demonstration. The human transparency dashboards are stylized using vanilla CSS variables, and the unittest coverage is pushed to exceed ninety percent. Final secret leak scanners are executed, and the repository is populated with comprehensive README documentation, licensing frameworks, and contributor attribution schemas.

## **Licensing and Attribution Notice**

To safeguard the integrity of this reference implementation while fostering an open, educational community, MemoryEndpoints.com is released under the MemoryEndpoints Public Source-Available License (MEPSAL). This restrictive commons license model is meticulously crafted to balance open access with rigid protections against software plagiarism and the unauthorized hosting of competing commercial services.
Under the MEPSAL framework, users are granted worldwide, non-exclusive rights to inspect, audit, modify, and utilize the codebase for internal study, security evaluation, and the submission of collaborative upstream contributions. Crucially, the license explicitly prohibits the use of the source code, or any derivative architecture thereof, to host a public or commercial Multi-Agent Transactive Memory platform that competes directly with the official MemoryEndpoints.com service.
Furthermore, any individual or organization that utilizes this repository to construct adjacent client libraries or testing frameworks must strictly adhere to the project's attribution rules. All derived works must prominently retain the original copyright headers, include the unbroken text of the NOTICE file, and provide explicit, direct hyperlinking back to the upstream MemoryEndpoints.com repository. The contributor guidelines, clearly delineated within the NOTICE file, stipulate that any code modifications or structural enhancements submitted to the repository via pull requests irrevocably grant the originators the perpetual right to distribute those contributions under the MEPSAL model.
The repository's README.md must display the following mandatory language prominently at the document header:

## **Licensing & Originality Notice**

MemoryEndpoints.com is released under the **MemoryEndpoints Public Source-Available License (MEPSAL)**. While we encourage viewing, personal learning, and collaborative contributions, **unauthorized commercial hosting, rebranding, or claiming this work as your own original product is strictly prohibited**.
If you use this project for study or build adjacent libraries, you must:

1. Keep all original copyright notices and license files intact.
2. Link back directly to [MemoryEndpoints.com](https://memoryendpoints.com) and the upstream repository.
3. State modifications clearly under our Contributor Attribution Rules (see NOTICE).

**Report Path Destination:**
E:\\MemoryEndpoints.com\\docs\\reports\\architecture-api-contract.md
**Highest-Risk Design Decisions:**

1. **Pure WSGI Custom Router over Established Frameworks:** Foregoing hardened frameworks like Flask drastically increases the architectural complexity of request parsing, URL decoding, and exception handling. A vulnerability in the custom urllib.parse implementation or a failure to properly close byte streams could expose the system to HTTP request smuggling or unhandled edge-case panics, leading to denial of service.
2. **Pure Python SQL Migration Engine:** Depending on sequential, custom SQL transaction scripts rather than industry-standard tools (e.g., Alembic) requires flawless schema state management. If a migration script fails mid-execution and the transaction block does not trigger a perfect rollback, the relational database schema could fragment, rendering the MATM repository unrecoverable.
3. **Regex-Based PII Redaction at the Persistence Gate:** Attempting to sanitize high-value payloads prior to database insertion using regular expressions is inherently brittle. Heavily obfuscated, encoded, or uniquely formatted API keys might evade the src/core/security.py sweeps, resulting in persistent credential leaks residing within the shared MATM logs.

**Recommended Milestone 1 File List:**

* src/passenger\_wsgi.py (WSGI callable entry point)
* src/core/router.py (Custom HTTP request dispatcher and CORS handler)
* src/handlers/static\_handler.py (Byte-streaming logic for static text/HTML responses)
* public/index.html (Accessible HTML5 human homepage)
* public/css/styles.css (Vanilla CSS grid and variable styling)
* public/robots.txt (Standard search and AI crawler directives)
* public/llms.txt (Markdown-based LLM orientation sitemap)
* public/ai.txt (AIPREF training consent and scraping declarations)
* public/ai-manifest.json (Han UI mapping instructions for visual automation agents)
* public/.well-known/mcp.json (Model Context Protocol base schema)
* public/.well-known/ai-agent.json (Agent discovery and identity definitions)

#### **Works cited**

1. Multi-Agent Transactive Memory \- arXiv, [https://arxiv.org/html/2606.19911v1](https://arxiv.org/html/2606.19911v1)
2. Multi-Agent Transactive Memory \- arXiv, [https://arxiv.org/pdf/2606.19911](https://arxiv.org/pdf/2606.19911)
3. Paper page \- Multi-Agent Transactive Memory \- Hugging Face, [https://huggingface.co/papers/2606.19911](https://huggingface.co/papers/2606.19911)
4. Passenger sub uri's \- nginx \- Stack Overflow, [https://stackoverflow.com/questions/59954886/passenger-sub-uris](https://stackoverflow.com/questions/59954886/passenger-sub-uris)
5. How to work with Python App \- Hosting \- Namecheap.com, [https://www.namecheap.com/support/knowledgebase/article.aspx/10048/2182/how-to-work-with-python-app/](https://www.namecheap.com/support/knowledgebase/article.aspx/10048/2182/how-to-work-with-python-app/)
6. Content Quality and Discovery for ARuntime.com \- aRuntime.com, [https://aruntime.com/ai-ready-web/](https://aruntime.com/ai-ready-web/)
7. About Teleodynamic AI and the Source Ecosystem, [https://teleodynamic.com/about/](https://teleodynamic.com/about/)
8. MikeKappel.com: Skills, [https://mikekappel.com/](https://mikekappel.com/)
9. LMRuntime.com Public Discovery Policy | Machine-Readable Files and Citation Boundaries, [https://lmruntime.com/ai-ready-web/](https://lmruntime.com/ai-ready-web/)
10. From browser to agent: why Agentic Browsing changes the role of the website \- Gautier Dorval, [https://gautierdorval.com/en/blog/agentic-era/browser-to-agent-agentic-browsing-website-role/](https://gautierdorval.com/en/blog/agentic-era/browser-to-agent-agentic-browsing-website-role/)
11. AI Discovery Files | Market Disruptors AI Visibility Agency, [https://marketdisruptorsagency.com/ai-discovery](https://marketdisruptorsagency.com/ai-discovery)
12. ai.txt: A Domain-Specific Language for Guiding AI Interactions with the Internet \- arXiv, [https://arxiv.org/html/2505.07834v1](https://arxiv.org/html/2505.07834v1)
13. llms.txt vs robots.txt vs ai.txt: The Honest Guide to AI Crawler Control | Glasp, [https://glasp.co/articles/llms-txt-ai-crawler-control](https://glasp.co/articles/llms-txt-ai-crawler-control)
14. LLMS.txt Best Practices & Implementation Guide \- Rankability, [https://www.rankability.com/blog/llms-txt-best-practices/](https://www.rankability.com/blog/llms-txt-best-practices/)
15. llms.txt | Fern Documentation, [https://buildwithfern.com/learn/docs/ai-features/llms-txt](https://buildwithfern.com/learn/docs/ai-features/llms-txt)
16. AI Resources for Mambu Docs | Mambu Documentation Hub, [https://docs.mambu.com/documentation-guidelines/ai-resources/](https://docs.mambu.com/documentation-guidelines/ai-resources/)
17. Working with llms.txt | Platform Overview \- Mastercard Developers, [https://developer.mastercard.com/platform/documentation/agent-toolkit/working-with-llmstxt/](https://developer.mastercard.com/platform/documentation/agent-toolkit/working-with-llmstxt/)
18. draft-car-ai-txt-wellknown-00 \- AI.TXT: A Declaration File for AI Usage Preferences, Licensing, and Policy \- IETF Datatracker, [https://datatracker.ietf.org/doc/draft-car-ai-txt-wellknown/00/](https://datatracker.ietf.org/doc/draft-car-ai-txt-wellknown/00/)
19. draft-han-ai-manifest-01 \- AI Manifest: Embedded Workflow Instructions for AI Agents, [https://datatracker.ietf.org/doc/draft-han-ai-manifest/01/](https://datatracker.ietf.org/doc/draft-han-ai-manifest/01/)
20. AI Manifest: Embedded Workflow Instructions for AI Agents \- IETF, [https://www.ietf.org/archive/id/draft-han-ai-manifest-00.html](https://www.ietf.org/archive/id/draft-han-ai-manifest-00.html)
21. Connect Claude Code to tools via MCP, [https://code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp)
22. MCP Server Discovery: Implement .well-known/mcp.json (2026) | Ekamoira Blog, [https://www.ekamoira.com/blog/mcp-server-discovery-implement-well-known-mcp-json-2026-guide](https://www.ekamoira.com/blog/mcp-server-discovery-implement-well-known-mcp-json-2026-guide)
23. MCP (Model Context Protocol) Guide: AI Tool Integration | Meta Intelligence, [https://www.meta-intelligence.tech/en/insight-mcp](https://www.meta-intelligence.tech/en/insight-mcp)
24. agents.txt — Open Standard for AI Agent Discovery \- GitHub, [https://github.com/asturwebs/agents-txt](https://github.com/asturwebs/agents-txt)
25. ai/agent.json at main · team-telnyx/ai \- GitHub, [https://github.com/team-telnyx/ai/blob/main/agent.json](https://github.com/team-telnyx/ai/blob/main/agent.json)
26. LMRuntime Generated-Answer Source Map | Canonical Package Citations, [https://lmruntime.com/generative-engine-optimization/](https://lmruntime.com/generative-engine-optimization/)
27. Newest 'cpanel' Questions \- Stack Overflow, [https://stackoverflow.com/questions/tagged/cpanel?tab=Newest](https://stackoverflow.com/questions/tagged/cpanel?tab=Newest)
28. IAAR-Shanghai/Awesome-AI-Memory \- GitHub, [https://github.com/IAAR-Shanghai/Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory)
29. Invisible Site Ranks \#1 in AI Search — How Structured Data Alone Fooled Perplexity | LinkSurge Blog — SEO, AIO & GEO Tools, [https://linksurge.jp/blog/en/phantom-authority-invisible-website-ai-citation-2026/](https://linksurge.jp/blog/en/phantom-authority-invisible-website-ai-citation-2026/)
