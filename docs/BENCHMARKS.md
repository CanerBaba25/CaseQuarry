# Benchmarks

The multi-million-email capacity target has not been met or claimed. Generator support for 2,000,000 records is not proof of ingest/search capacity. Actual measurements, corpus mix, failures and hardware must be recorded before changing that claim.

The local owner workspace has a streaming MBOX generator and private acceptance harness. These QA assets and test files are excluded from the public source distribution; the commands below apply only where those local assets are present:

```sh
uv run python scripts/generate_synthetic_emails.py --count 10000 --documents 100 --seed 42 --output .data/synthetic-10k
```

The generator uses 24 fictional contacts, explicit reply headers, Unicode subjects, deliberately malformed dates, exact duplicates, PDF attachments, contradictory statements and hostile document instructions. Separate adversarial fixtures exercise corrupt PDFs, unsupported adapters, archive traversal and excessive expansion. No client corpus is included.

`golden.json` defines occurrence/attachment/duplicate/query counts and mixed-document hashes. PNG images are preserved but require an OCR runtime for text; they must not be counted as fully extracted when OCR is unavailable. Import only `emails.mbox` plus `documents/` for benchmark totals; example EML copies and adversarial fixtures are separate tests.

The benchmark task runs a real isolated API/worker workflow and writes its result under ignored `.data/benchmarks/`. Each report must state the backend, email/document count, ingestion elapsed time/throughput, query p50/p95/p99, discovered/indexed/error counts, stored disk bytes and available memory/CPU observations. Browser acceptance and a representative production host remain separate gates.

## Recorded 10,000-email development run — October 12, 2026

Backend: SQLite with the embedded durable SQL worker, Python 3.12.15, Windows AMD64. Host: Intel Core i9-13900KF, 32 logical CPUs; reported physical memory 68,424,015,872 bytes. This was a synthetic development corpus in a Windows working directory, not a representative firm-server production trial.

| Measurement | Observed result |
|---|---:|
| Email occurrences | 10,000 |
| Linked attachment occurrences | 801 |
| Mixed documents / preserved MBOX container | 100 / 1 |
| Total preserved evidence/source occurrences | 10,902 |
| Unique original objects / exact duplicate occurrences | 10,703 / 199 |
| Indexed / partial / stored container | 10,891 / 10 / 1 |
| Failed / unsupported / pending | 0 / 0 / 0 |
| Import time, including mixed documents | 163.49 seconds |
| Email occurrences per second, including document overhead | 61.17 |
| Grouped phrase query p50 / p95 / p99 | 187.10 / 244.94 / 249.71 ms |
| API and embedded worker peak resident memory | 157.20 MiB |
| API and embedded worker CPU time | 128.67 seconds |
| Preserved original logical bytes | 15,137,951 |
| Run-directory logical bytes at measurement | 105,489,815 |

All 100 mixed-document originals matched their deterministic golden SHA-256 and passed fresh stored-byte verification. Ninety documents had their expected extracted text; ten PNGs remained visibly partial because Tesseract was unavailable. Twenty-five additional original samples passed verification. Golden phrase totals were exactly 1,430 for `"payment approved"`, 780 for `"payment was denied"` and 600 for `"shipment delay"`. The audit chain passed verification, and the final run had no rate-limit retries.

Query percentiles use only 15 samples across three known phrase queries with sender grouping; they do not establish a production latency SLA. Run-directory bytes include database/derivative/log files at measurement and are not allocated physical disk usage. Generator/browser/system-wide resource peaks were outside the measured API process. The local report is `.data/benchmarks/20261012T215728-10000-8a2bc3/report.json`.

An earlier local run exposed an XLSX path-handling failure and excessive status polling; both were corrected before the recorded run. The table above reflects the final completed run. PostgreSQL/Docker/OpenSearch and 100k/1m/2m capacity remain unvalidated.
