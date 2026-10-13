# Optional analysis policy

Preservation, keyword search, review, redaction and production work without a model. Local Ollama processing and bring-your-own-key cloud processing are optional. Every matter starts without model consent; every firm's cloud policy starts disabled. A configured key or available server capability authorizes no evidence transmission by itself.

## Consent and identity

Local processing requires an enabled server configuration, an installed local model and explicit consent from an active matter lead. Its matter policy uses `provider: "local"` and `data_sharing: "off"`.

Cloud processing requires all of the following:

1. The server operator allows the cloud capability.
2. An active firm administrator explicitly approves the selected provider in the firm's cloud policy.
3. An active matter lead explicitly enables that provider and external data sharing for the matter.
4. The requesting user has their own encrypted credential and compatible model configuration for that provider.
5. That user confirms external transmission and supplies a purpose for each selected or searched job.

Saving a credential or changing firm policy does not change existing local matter consent. There is no fallback to another user's key, a shared firm key or another provider. Stale firm and matter policy edits can be rejected using their displayed `expected_revision`. The worker captures consent and credential revisions, then rechecks active identity, matter membership, current policy, provider configuration and source integrity before an external request and again before publishing its response. Revoked or changed authorization prevents publication; it cannot recall evidence already transmitted or reverse vendor charges.

## Evidence remains data

Retrieved passages are supplied separately from system instructions as untrusted JSON. The adapters offer no shell, browser, filesystem, database or action tools. Instructions inside evidence cannot grant access to another matter or change a review decision. Provider responses requesting tools, refusing the required format or returning unsupported content are rejected.

The current mode is **extractive quotations**. Each published claim must be an exact contiguous substring of every cited retrieved span. Unknown, cross-matter, fabricated and paraphrased citations fail validation. This verifies the quotation's source, not the truth of the source or its legal meaning. A hostile source can still contain a misleading quotation; human context review remains necessary.

Original evidence and extracted artifacts retain independent hashes. Citations preserve evidence, source occurrence, immutable artifact version, span offsets and quotation hashes. Reprocessing does not rewrite earlier artifacts. Valid earlier findings remain readable through their version links with a superseded-source warning; accepting a superseded finding requires rerunning current analysis. Tampered originals, artifacts or stored quotations block access. Suspected or confirmed privileged evidence and quarantined items are excluded from model retrieval and counted in coverage. A source becoming restricted during a request prevents publication.

Model finding acceptance or rejection changes only the finding's human review state. It does not mark evidence responsive, decide privilege, merge identities, establish facts or approve a production.

## Bounded retrieval and transport

Each job selects at most 50 items and retrieves at most 40 current spans, with up to 1,600 characters per span. Retrieval currently takes the first eligible span of each selected item; it does not scan every page of a long document. Coverage reports total matches, selected and processed items, available and retrieved spans, restricted and unsearchable items, partial processing, truncation and sampling. Empty retrieval completes with an insufficiency message and makes no provider request.

Cloud requests use fixed official HTTPS endpoints for OpenAI Responses, Google Gemini, xAI chat completions and Anthropic Messages. User-supplied origins, URL-shaped models, redirects and environment proxy settings are not accepted. Requests contain the question, task and selected extracted passages with citation metadata; originals and full native attachments are not uploaded by these adapters. Request bodies are limited to 128 KiB, response bodies to 256 KiB and requested output to 2,048 tokens. Connect timeout is three seconds; individual network operations have a ten-second timeout. Incoming raw chunks are also checked against a 35-second elapsed response budget. Compressed responses are rejected. These limits are not a monetary spending guarantee.

Authentication, billing/rate, timeout, incomplete and malformed responses produce sanitized failure codes. Raw provider error bodies, API keys and diagnostic excerpts are not returned or recorded in audit metadata. No automatic paid retry or provider failover occurs. A recorded transmission attempt means the worker was about to make an external request; it does not prove receipt or successful completion. Charges may apply to failed or rejected results.

## Credentials and retention

API keys are encrypted with Fernet using a private server master key outside the database. Encryption envelopes bind tenant, user, provider and credential identity. Missing or invalid master keys prevent saving; there is no plaintext fallback. User APIs expose only masked suffixes, model configuration, revision and `saved_not_tested` status. Masked placeholders cannot overwrite keys. Revocation clears the active encrypted value, invalidates queued work and records an audit event without the key. Older encrypted database backups remain subject to the operator's retention policy.

Protect the master key, database, object storage and backups independently. A privileged server operator with both the master key and database can decrypt credentials; application access controls do not replace host security. Losing or replacing the master key without a deliberate migration makes existing credentials unusable. Revoke keys in the vendor account as well when a key may have been exposed.

OpenAI requests set `store: false`; this does not establish zero data retention. Each vendor's current account, retention, training, region and billing terms still apply. Review those terms before authorizing confidential evidence. Consult [OpenAI's data controls](https://developers.openai.com/api/docs/guides/your-data) and the chosen vendor's account documentation. Reported token counts are recorded when available; no dollar estimate or vendor pricing guarantee is calculated.

## Local runtime isolation

The Ollama adapter accepts a literal loopback HTTP(S) origin, such as `http://127.0.0.1:11434`, rejects redirects and prohibits model identifiers containing `cloud`. Enable `CASEQUARRY_AI_ENABLED`, configure an installed `CASEQUARRY_AI_MODEL`, then obtain matter-lead consent. Set `OLLAMA_NO_CLOUD=1` in the Ollama daemon's own environment. Loopback transport cannot attest that another daemon, proxy or runtime is offline; restrict that runtime's outbound network access when evidence policy requires it. Models are separately installed components with their own licenses and hardware requirements.

## Validation boundary

Regression checks exercise the actual routed consent and credential flows, official HTTP request schemas, structured response envelopes, identity isolation, revocation, source hashes, quotation validation and failure handling using synthetic evidence and controlled HTTP transports. The integrated cloud flow has also been exercised against the real PostgreSQL database. No supplied live vendor API key or paid request was available for release validation. Saving remains explicitly untested until a user invokes an authorized job. Live account access, selected-model compatibility, model quality, vendor retention behavior and billing outcomes are not certified by these checks.

See [the cloud configuration guide](CLOUD_AI_GUIDE.md) for operator and reviewer steps.
