"""Real isolated API import/search/integrity benchmark using synthetic fixtures."""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.generate_synthetic_emails import generate

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], ratio: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * ratio))]


def process_resources(pid: int) -> dict:
    """Measure the isolated API (including embedded worker), without extra dependencies."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (field, ctypes.c_size_t)
                for field in [
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                ]
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(MemoryCounters),
            wintypes.DWORD,
        ]
        kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return {"measurement": "unavailable"}
        try:
            counters = MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
            memory_ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            cpu_ok = kernel.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)
            )
            result = {"measurement": "Windows process counters; API and embedded worker"}
            if memory_ok:
                result["peak_resident_bytes"] = counters.PeakWorkingSetSize
            if cpu_ok:
                result["cpu_seconds"] = (
                    (system.dwHighDateTime << 32)
                    + system.dwLowDateTime
                    + (user.dwHighDateTime << 32)
                    + user.dwLowDateTime
                ) / 10_000_000
            return result
        finally:
            kernel.CloseHandle(handle)
    try:
        status = Path(f"/proc/{pid}/status").read_text()
        high = next(int(line.split()[1]) * 1024 for line in status.splitlines() if line.startswith("VmHWM:"))
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "measurement": "Linux proc counters; API and embedded worker",
            "peak_resident_bytes": high,
            "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
        }
    except (OSError, ValueError, StopIteration):
        return {"measurement": "unavailable on this platform; observe externally"}


def run_benchmark(output: Path, count: int = 10000) -> dict:
    if count < 1 or count > 2_000_000:
        raise ValueError("Count must be 1..2000000")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"-{count}-{secrets.token_hex(3)}"
    directory = ROOT / ".data" / "benchmarks" / run_id
    directory.mkdir(parents=True)
    dataset = output.resolve()
    if not (dataset / "golden.json").exists():
        generate(dataset, count, 42, 100)
    golden = json.loads((dataset / "golden.json").read_text(encoding="utf-8"))
    if golden["email_occurrences"] != count:
        raise ValueError("Dataset count differs from --count; generate a fresh --output directory")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    setup_token = secrets.token_urlsafe(48)
    env = {
        **os.environ,
        "CASEQUARRY_ENVIRONMENT": "test",
        "CASEQUARRY_DATABASE_URL": "sqlite:///" + (directory / "benchmark.db").as_posix(),
        "CASEQUARRY_STORAGE_ROOT": str(directory / "private"),
        "CASEQUARRY_SETUP_TOKEN": setup_token,
        "CASEQUARRY_WORKER_MODE": "embedded",
        "CASEQUARRY_AI_ENABLED": "false",
        "CASEQUARRY_ALLOW_REMOTE_AI": "false",
        "CASEQUARRY_MAX_UPLOAD_BYTES": str(
            max(256 * 1024 * 1024, (dataset / "emails.mbox").stat().st_size + 1024)
        ),
        "CASEQUARRY_MAX_CASE_BYTES": str(max(20 * 1024**3, (dataset / "emails.mbox").stat().st_size * 4)),
    }
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    report = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "backend": "SQLite development / embedded durable SQL worker",
        "hardware": {
            "os": platform.system(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
        },
        "dataset": {
            "seed": golden["seed"],
            "email_occurrences": count,
            "documents": golden["documents"],
            "attachment_occurrences": golden["email_attachment_occurrences"],
            "duplicate_email_occurrences": golden["exact_duplicate_occurrences"],
        },
        "scope": "Local synthetic import/search/integrity workflow; not a production capacity certification",
        "status": "running",
        "limitations": [
            "No Docker/PostgreSQL/OpenSearch performance validation",
            "No GPU/OCR throughput claim",
            "No browser E2E measurement",
            "Memory/CPU counters cover the API and embedded worker; generator, browser and system-wide peaks require separate observation",
            "No promise that a 2-million run fits this host's resources",
        ],
    }
    destination = directory / "report.json"
    print(
        f"Benchmark {run_id}: {count} synthetic emails and {golden['documents']} documents; results in {destination}",
        flush=True,
    )
    with (directory / "server.log").open("w", encoding="utf-8") as logs:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "casequarry.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            stdout=logs,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1", timeout=300) as client:
                for _ in range(200):
                    try:
                        if client.get("/health").is_success:
                            break
                    except httpx.RequestError:
                        pass
                    if process.poll() is not None:
                        raise RuntimeError("Benchmark API failed to start; inspect its local server.log")
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Benchmark API did not become healthy")

                def request(method: str, route: str, **kwargs):
                    for attempt in range(4):
                        response = client.request(method, route, **kwargs)
                        if response.status_code != 429 or attempt == 3:
                            break
                        delay = min(60, max(1, float(response.headers.get("Retry-After", "1"))))
                        report.setdefault("rate_limit_retries", []).append(
                            {"route": route, "wait_seconds": delay}
                        )
                        print(f"Rate limited; honoring Retry-After for {delay:g} seconds.", flush=True)
                        time.sleep(delay)
                    if not response.is_success:
                        raise RuntimeError(
                            f"Benchmark API returned HTTP {response.status_code} at {route}: {response.text[:400]}"
                        )
                    return response.json()

                email = f"benchmark-{run_id}@synthetic.example"
                password = secrets.token_urlsafe(32)
                request(
                    "POST",
                    "/setup",
                    json={
                        "token": setup_token,
                        "firm_name": "Synthetic Benchmark",
                        "name": "Synthetic Operator",
                        "email": email,
                        "password": password,
                    },
                )
                token = request("POST", "/auth/token", json={"email": email, "password": password})[
                    "access_token"
                ]
                client.headers["Authorization"] = "Bearer " + token
                matter = request(
                    "POST",
                    "/cases",
                    json={"matter_number": "SYN-" + run_id, "title": "Synthetic scale validation"},
                )
                case_id = matter.get("id", matter.get("case_id"))
                base = f"/cases/{case_id}"
                started = time.perf_counter()
                batches = []
                for paths, label in [
                    ([dataset / "emails.mbox"], "Synthetic MBOX"),
                    (sorted((dataset / "documents").iterdir()), "Synthetic mixed documents"),
                ]:
                    for start in range(0, len(paths), 25):
                        with ExitStack() as stack:
                            files = [
                                (
                                    "files",
                                    (
                                        path.name,
                                        stack.enter_context(path.open("rb")),
                                        "application/octet-stream",
                                    ),
                                )
                                for path in paths[start : start + 25]
                            ]
                            batch = request(
                                "POST",
                                base + "/imports",
                                files=files,
                                data={"source_label": label, "custodian_name": "Synthetic custodian"},
                            )
                        batch_id = batch.get("batch_id", batch.get("id"))
                        deadline = time.monotonic() + max(600, count * 0.25)
                        while time.monotonic() < deadline:
                            status = request("GET", base + f"/imports/{batch_id}")
                            state = status.get("state", "").lower()
                            if state in {"completed", "complete", "partial", "failed", "cancelled"}:
                                if state in {"failed", "cancelled"}:
                                    raise RuntimeError("Synthetic import failed; see batch status/errors")
                                batches.append(status)
                                break
                            time.sleep(1)
                        else:
                            raise TimeoutError(
                                "Import benchmark time budget elapsed; no capacity claim is made"
                            )
                        print(f"Completed import batch {batch_id}", flush=True)
                elapsed = time.perf_counter() - started
                report["ingestion"] = {
                    "seconds": elapsed,
                    "email_occurrences_per_second": count / elapsed,
                    "batches": batches,
                    "stats": request("GET", base + "/stats"),
                }
                email_result = request(
                    "POST",
                    base + "/search",
                    json={"query": "", "filters": {"item_types": ["email"]}, "page_size": 1},
                )
                assert email_result["total_hits"] == count, (
                    f"Email count mismatch: {email_result['total_hits']} != {count}"
                )
                documents = request(
                    "POST", base + "/search", json={"query": "filename:synthetic-", "page_size": 200}
                )
                assert documents["total_hits"] == golden["documents"], (
                    "Mixed-document count differs from golden inventory"
                )
                document_items = {item["original_name"]: item for item in documents["items"]}
                for expected in golden["document_manifest"]:
                    item = document_items[expected["name"]]
                    assert item["sha256"] == expected["sha256"], (
                        "Mixed-document original hash differs from fixture"
                    )
                    if expected["expected_text"]:
                        assert (
                            item["parser_state"]
                            not in {"failed", "unsupported", "partial", "quarantined", "locked"}
                            and item.get("snippet", "").strip()
                        ), f"Expected document text was not extracted: {expected['name']}"
                    elif not shutil.which("tesseract"):
                        assert item["parser_state"] == "partial", (
                            "Unavailable image OCR must remain visibly partial"
                        )
                    verified = request("POST", base + f"/evidence/{item['evidence_id']}/verify")
                    assert verified.get("valid"), "Mixed-document stored bytes failed hash verification"
                report["mixed_documents"] = {
                    "preserved_and_hash_verified": len(document_items),
                    "expected_searchable_without_ocr": golden["searchable_documents_without_ocr"],
                    "all_expected_text_extracted": True,
                    "parser_states": dict(Counter(item["parser_state"] for item in document_items.values())),
                }
                measurements = []
                matched = {}
                for query, expected in golden["queries"].items():
                    for _ in range(5):
                        tick = time.perf_counter()
                        result = request(
                            "POST",
                            base + "/search",
                            json={"query": query, "page_size": 25, "group_by": "sender"},
                        )
                        measurements.append((time.perf_counter() - tick) * 1000)
                        assert result["total_hits"] == expected, (
                            f"Golden query mismatch: {query}: {result['total_hits']} != {expected}"
                        )
                    matched[query] = expected
                report["search"] = {
                    "golden_counts": matched,
                    "samples": len(measurements),
                    "latency_ms": {
                        "p50": percentile(measurements, 0.5),
                        "p95": percentile(measurements, 0.95),
                        "p99": percentile(measurements, 0.99),
                    },
                }
                sample = request("POST", base + "/search", json={"query": "", "page_size": 25})
                for item in sample["items"]:
                    item_id = item.get("evidence_id", item.get("id"))
                    verified = request("POST", base + f"/evidence/{item_id}/verify")
                    assert verified.get("valid", verified.get("verified", verified.get("ok", False))), (
                        f"Original integrity failed: {item_id}"
                    )
                report["integrity"] = {"sampled_items": len(sample["items"]), "all_sampled_valid": True}
                report["audit"] = request("POST", base + "/audit/verify")
                report["disk_bytes"] = sum(
                    path.stat().st_size for path in directory.rglob("*") if path.is_file()
                )
                report["status"] = "passed_recorded_scope"
        except Exception as error:
            report["status"] = "failed"
            report["error"] = str(error)
            raise
        finally:
            # Windows venv's python.exe can be a redirector; measure the actual
            # uvicorn runtime identified by its own startup log, not that launcher.
            logs.flush()
            startup = (directory / "server.log").read_text(encoding="utf-8", errors="replace")
            runtime = re.search(r"Started server process \[(\d+)\]", startup)
            runtime_pid = int(runtime.group(1)) if runtime else process.pid
            report["resources"] = process_resources(runtime_pid)
            report["finished_at"] = datetime.now(UTC).isoformat()
            destination.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
            from scripts.tasks import stop_children

            stop_children([process])
    return report
