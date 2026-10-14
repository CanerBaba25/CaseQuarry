# Configure an optional cloud provider

CaseQuarry supports user-owned keys for OpenAI API, Google Gemini API, xAI Grok API, Anthropic Claude API and Kimi API (Moonshot). Core evidence work requires none of them. The provider account, key and model must support the implemented structured-output API; a consumer chat subscription is not a substitute for API access. No model is selected automatically, and saving a key makes no vendor request.

## Prepare the server

The server needs a private Fernet master key in `CASEQUARRY_PROVIDER_KEY_ENCRYPTION_KEY`. Setup generates one for the configured deployment; an existing installation must retain its own key. Keep it outside Git and the database, restrict access to the API and worker service accounts, and provide the same key to both processes. Back it up separately and securely. Missing or invalid keys cause saving to fail without storing plaintext. Do not replace a working master key casually: existing credentials will no longer decrypt.

`CASEQUARRY_ALLOW_REMOTE_AI=false` is the operator's kill switch. Allowing the capability leaves the firm's cloud policy disabled until a firm administrator explicitly approves providers. The API/worker needs outbound HTTPS access only to the selected official hosts; PostgreSQL and object storage should remain private. A deployment requiring network isolation can keep cloud capability off and continue using core workflows or a separately isolated local runtime.

## Save your own credential

Open provider settings while signed in as the user who will request analysis. Choose the vendor, paste a complete API key and enter a compatible model identifier from that API account. Save. The status is **saved, not tested**: it confirms encrypted storage, not vendor authentication, billing balance or model availability.

Other users receive their own credential list. Administrators cannot supply a different user's key through this interface. To change only a model, leave the key untouched; the API supports omitting `api_key` and preserves the existing encrypted value. Never paste a masked placeholder as a replacement key. Saving uses the displayed revision to reject concurrent changes. Revoking removes the active stored key and invalidates pending jobs using it; separately revoke it at the vendor if it may have been exposed.

## Obtain firm and matter consent

A firm administrator opens cloud policy, selects allowed vendors, states the authorized purpose and explicitly confirms external processing. The policy takes effect only while its approving administrator remains active with that role. Reload if another administrator changed its revision.

A matter lead then opens the matter's model policy and selects that approved vendor, external sharing and a purpose. Explicitly confirm the change. Choosing a cloud provider replaces that matter's selected processing mode; changing credentials or firm policy alone preserves local-only consent. A reviewer with matter access may request a job after the lead approves the matter, using that reviewer's own saved key and model.

Every cloud job requires a fresh external-transmission confirmation and purpose. Carefully choose the evidence scope and question before submitting. Selected extracted passages, their citation metadata and the question leave the server. These adapters do not upload original files. Restricted evidence is omitted, and the completed coverage must be checked for partial processing, sampling and truncation.

Confirmation binds the displayed provider, model credential, matter policy and firm cloud policy. If any of them changes before submission, review the new configuration and confirm again. An old confirmation cannot silently authorize a replacement provider or model.

## Review results and failures

The current result is cited source quotations. It is not an inferred legal summary. Open each citation, verify the passage and context, then accept or reject the finding with a reason. Finding review leaves evidence decisions unchanged. Earlier immutable citation links remain usable after reprocessing when their hashes pass verification; a superseded-source warning requires a new run before accepting current analysis.

The job shows the configured provider/model, reported model identifier when safely available, coverage, transmission-attempt state and reported token counts. Pricing is controlled by your vendor account. The output limit and request-size cap do not guarantee a dollar budget. A failure after transmission may still incur charges, and revocation cannot recall previously transmitted text. No automatic paid retry occurs.

An authentication failure requires checking your own API key and account. A rate or billing failure requires reviewing vendor limits. A model/request rejection requires a model compatible with the vendor's structured-output endpoint. Disabled or changed consent, membership, privilege, credentials or source hashes requires resolving that change and submitting a new authorized scope. Raw vendor diagnostics are withheld to avoid returning secrets or evidence.

## API contract

All paths below are under `/api/v1`. Cookie-authenticated mutations require `X-CSRF-Token`; bearer authentication follows the same user and matter permissions.

| Operation | Route | Required behavior |
| --- | --- | --- |
| List your saved providers | `GET /ai/credentials` | Five redacted entries; keys are never returned |
| Save or update your provider | `PUT /ai/credentials/{provider}` | `model`, optional complete `api_key`, `expected_revision` (zero on first save) |
| Revoke your provider | `DELETE /ai/credentials/{provider}` | JSON body with meaningful `reason` |
| Read firm cloud policy | `GET /ai/cloud-policy` | Disabled by default; includes effective state and revision |
| Change firm cloud policy | `PATCH /ai/cloud-policy` | Firm administrator; `enabled`, `allowed_providers`, `confirmed`, `reason`, displayed `expected_revision` |
| Read or change matter policy | `GET/PATCH /cases/{id}/ai/policy` | PATCH requires matter lead; `enabled`, `provider`, `data_sharing`, `confirmed`, `reason`, displayed `expected_revision` |
| Request quoted analysis | `POST /cases/{id}/ai/ask` or `/summarize` | Bounded `evidence_ids` or `query_spec`, question/style; cloud also requires `confirmed_external: true`, meaningful `reason` and the four confirmed snapshot fields below |
| Inspect work and findings | `GET /cases/{id}/ai/jobs` or `/jobs/{job_id}` | Current matter access and source integrity required |
| Review a finding | `POST /cases/{id}/ai/findings/{finding_id}/review` | Authorized review role; `decision: "accept"` or `"reject"`, meaningful `reason` |

Provider IDs are `openai`, `gemini`, `xai`, `anthropic` and `kimi`. Local mode remains `provider: "local", data_sharing: "off"`; cloud consent uses `data_sharing: "on"`. Stale credential, firm and matter edits return conflict responses. Never include a key in questions, notes or purpose fields.

Starting with 0.7.0, cloud job requests must echo `expected_provider`, `expected_policy_revision`, `expected_credential_revision` and `expected_firm_policy_revision`. Capture them when the user confirms the displayed configuration from `GET /cases/{id}/ai/policy`, using its `provider`, `revision`, `credential_revision` and `firm_policy_revision` values respectively. Credential revision also binds the selected model. Missing fields return HTTP 422 `AI_CONFIRMATION_REQUIRED`; changed configuration returns HTTP 409 `AI_CONFIRMATION_STALE` before queueing or transmission. Require a new reviewed confirmation rather than silently updating the snapshot. Local requests do not require these fields.

## Implemented vendor APIs

| Provider | Fixed endpoint | Structured output |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1/responses` | Strict JSON schema in `text.format`; response storage disabled |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` | JSON schema in `generationConfig.responseFormat.text` |
| xAI | `https://api.x.ai/v1/chat/completions` | Strict JSON schema in `response_format` |
| Anthropic | `https://api.anthropic.com/v1/messages` | JSON schema in `output_config.format` |
| Kimi (Moonshot) | `https://api.moonshot.ai/v1/chat/completions` | JSON schema in `response_format`; `max_completion_tokens` limits output |

These adapters follow the official [OpenAI structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), [Gemini generation reference](https://ai.google.dev/api/generate-content), [xAI structured-output guide](https://docs.x.ai/developers/model-capabilities/text/structured-outputs) and [Anthropic structured-output guide](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). Review model compatibility and current account terms before use. OpenAI's `store: false` is a request setting, not a zero-retention certification; other vendors' policies remain account dependent.

Kimi follows the official [Moonshot Chat Completions contract](https://platform.kimi.ai/docs/api/chat). Use a Kimi Open Platform key for the fixed global `api.moonshot.ai` endpoint and a model available to that API account. [Kimi chat membership and Kimi Code credentials use different products and billing](https://www.kimi.com/en/help/kimi-code/faq); they do not replace this API key. Custom endpoints, the mainland endpoint and Kimi Code's coding endpoint are not selected by this adapter. No model is chosen automatically. Incompatible models fail visibly without a fallback or paid retry.

Release checks use synthetic evidence and controlled HTTP responses, including the actual PostgreSQL-backed application flow. No live vendor account or paid invocation was tested. See [analysis safety and validation limits](AI_SAFETY.md) for privacy, integrity and coverage details.
