"""Fixed official HTTPS APIs; bounded source-only requests and sanitized failures."""

import json
import re
import time

import httpx
from fastapi import HTTPException

from .provider_service import provider, validate_model
from .security import fail

MAX_INPUT_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_OUTPUT_TOKENS = 2048
SCHEMA = {"type": "object", "properties": {"findings": {"type": "array", "items": {"type": "object", "properties": {"claim": {"type": "string"}, "citation_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["claim", "citation_ids"], "additionalProperties": False}}}, "required": ["findings"], "additionalProperties": False}


def request_data(job, sources, instructions, api_key):
    selected = provider(job.provider)
    validate_model(job.model)
    if job.provider_endpoint != selected["endpoint"]:
        fail(409, "AI_CONFIGURATION_CHANGED", "The configured provider origin no longer matches the official endpoint.")
    text = json.dumps({"question": job.question, "task": job.task, "untrusted_sources": sources}, ensure_ascii=False, separators=(",", ":"))
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    if job.provider == "openai":
        url = selected["endpoint"]
        headers["Authorization"] = "Bearer " + api_key
        body = {"model": job.model, "instructions": instructions, "input": [{"role": "user", "content": text}], "stream": False, "store": False, "max_output_tokens": MAX_OUTPUT_TOKENS, "text": {"format": {"type": "json_schema", "name": "casequarry_source_quotes", "strict": True, "schema": SCHEMA}}}
    elif job.provider == "xai":
        url = selected["endpoint"]
        headers["Authorization"] = "Bearer " + api_key
        body = {"model": job.model, "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": text}], "stream": False, "max_tokens": MAX_OUTPUT_TOKENS, "response_format": {"type": "json_schema", "json_schema": {"name": "casequarry_source_quotes", "strict": True, "schema": SCHEMA}}}
    elif job.provider == "gemini":
        url = selected["endpoint"] + job.model + ":generateContent"
        headers["x-goog-api-key"] = api_key
        body = {"systemInstruction": {"parts": [{"text": instructions}]}, "contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": {"candidateCount": 1, "maxOutputTokens": MAX_OUTPUT_TOKENS, "responseFormat": {"text": {"mimeType": "application/json", "schema": SCHEMA}}}}
    else:
        url = selected["endpoint"]
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        body = {"model": job.model, "system": instructions, "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}], "stream": False, "max_tokens": MAX_OUTPUT_TOKENS, "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}}
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_INPUT_BYTES:
        fail(413, "AI_INPUT_BUDGET", "The serialized cloud request exceeds 128 KiB. Select fewer items or shorter excerpts.")
    return url, headers, encoded


def _status(status):
    if status in {401, 403}:
        fail(503, "AI_PROVIDER_AUTH_FAILED", "The provider rejected authentication or account access. Update your own key and account permissions.")
    if status == 429:
        fail(503, "AI_PROVIDER_RATE_LIMITED", "The provider's rate or billing quota was reached. Review your account before explicitly retrying.")
    if status in {400, 404, 422}:
        fail(503, "AI_PROVIDER_REQUEST_REJECTED", "The provider rejected this model or structured-output request. Choose a compatible model available to your API account.")
    fail(503, "AI_PROVIDER_UNAVAILABLE", "The provider did not return a successful response. No automatic paid retry was made.")


def _usage(values):
    allowed = ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens", "promptTokenCount", "candidatesTokenCount", "totalTokenCount", "thoughtsTokenCount")
    return {key: value for key, value in values.items() if key in allowed and isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63} if isinstance(values, dict) else {}


def parse_response(identifier, value):
    if not isinstance(value, dict):
        fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider returned an invalid response envelope.")
    text, usage = [], {}
    if identifier == "openai":
        if value.get("status") != "completed":
            fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider response was not completed.")
        for item in value.get("output", []):
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider attempted an unavailable tool or action.")
            for block in item.get("content", []):
                if block.get("type") != "output_text":
                    fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider refused or returned unsupported content.")
                text.append(block.get("text", ""))
        usage = _usage(value.get("usage"))
    elif identifier == "xai":
        choices = value.get("choices", [])
        if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
            fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider response was incomplete.")
        message = choices[0].get("message", {})
        if message.get("role") != "assistant" or message.get("tool_calls") or message.get("refusal"):
            fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider refused or attempted an unavailable action.")
        text = [message.get("content", "")]
        usage = _usage(value.get("usage"))
    elif identifier == "gemini":
        choices = value.get("candidates", [])
        if len(choices) != 1 or choices[0].get("finishReason") != "STOP" or value.get("promptFeedback", {}).get("blockReason"):
            fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider response was blocked or incomplete.")
        for part in choices[0].get("content", {}).get("parts", []):
            if set(part) - {"text", "thought", "thoughtSignature"} or part.get("thought"):
                fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider returned unsupported or executable content.")
            text.append(part.get("text", ""))
        usage = _usage(value.get("usageMetadata"))
    else:
        if value.get("type") != "message" or value.get("role") != "assistant" or value.get("stop_reason") != "end_turn":
            fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider response was incomplete or requested an unavailable action.")
        for block in value.get("content", []):
            if block.get("type") != "text":
                fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider returned unsupported content.")
            text.append(block.get("text", ""))
        usage = _usage(value.get("usage"))
    if not text or not all(isinstance(part, str) for part in text):
        fail(503, "AI_PROVIDER_RESPONSE_INVALID", "No structured source quotation response was returned.")
    output = json.loads("".join(text))
    if not isinstance(output, dict) or set(output) != {"findings"}:
        fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider did not return the required quotation schema.")
    return output, usage


def generate(job, sources, instructions, api_key, output_type):
    url, headers, encoded = request_data(job, sources, instructions, api_key)
    deadline = time.monotonic() + 35
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(10, connect=3)) as client:
            with client.stream("POST", url, content=encoded, headers=headers) as response:
                if response.status_code != 200:
                    _status(response.status_code)
                if response.headers.get("content-encoding", "identity") != "identity":
                    fail(503, "AI_PROVIDER_RESPONSE_INVALID", "Compressed provider responses are not accepted.")
                content = bytearray()
                for chunk in response.iter_raw():
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
                        fail(503, "AI_PROVIDER_LIMIT", "The provider response exceeded its time or byte budget.")
                    content.extend(chunk)
        value = json.loads(content)
        output, usage = parse_response(job.provider, value)
        reported = value.get("model") or value.get("modelVersion")
        if isinstance(reported, str) and reported != api_key and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", reported) and not reported.startswith(("sk-", "AIza", "xai-")):
            usage["response_model"] = reported
        return output_type.model_validate(output), {**usage, "provider": job.provider, "input_bytes": len(encoded), "max_output_tokens": MAX_OUTPUT_TOKENS, "cost_estimate": None, "cost_status": "Provider account pricing and reported usage apply; no monetary estimate or spend guarantee was calculated."}
    except HTTPException:
        raise
    except httpx.TimeoutException:
        fail(503, "AI_PROVIDER_TIMEOUT", "The provider did not complete within the bounded request timeout. No automatic paid retry was made.")
    except Exception:
        fail(503, "AI_PROVIDER_RESPONSE_INVALID", "The provider response could not be safely validated. No finding was published.")
