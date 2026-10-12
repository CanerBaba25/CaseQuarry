# Benchmarks

The multi-million-email capacity target has not been met or claimed. Generator support for 2,000,000 records is not proof of ingest/search capacity. Actual measurements, corpus mix, failures and hardware must be recorded before changing that claim.

Generate a streaming MBOX and 100 mixed synthetic documents with:

```sh
uv run python scripts/generate_synthetic_emails.py --count 10000 --documents 100 --seed 42 --output .data/synthetic-10k
```

The generator uses 24 fictional contacts, explicit reply headers, Unicode subjects, deliberately malformed dates, exact duplicates, PDF attachments, contradictory statements and hostile document instructions. Separate adversarial fixtures exercise corrupt PDFs, unsupported adapters, archive traversal and excessive expansion. No client corpus is included.

`golden.json` defines occurrence/attachment/duplicate/query counts and mixed-document hashes. PNG images are preserved but require an OCR runtime for text; they must not be counted as fully extracted when OCR is unavailable. Import only `emails.mbox` plus `documents/` for benchmark totals; example EML copies and adversarial fixtures are separate tests.

The benchmark task runs a real isolated API/worker workflow and writes its result under ignored `.data/benchmarks/`. Each report must state the backend, email/document count, ingestion elapsed time/throughput, query p50/p95/p99, discovered/indexed/error counts, stored disk bytes and available memory/CPU observations. Browser acceptance and a representative production host remain separate gates.
