import hashlib
import io
import json
import mailbox
from contextlib import closing

from pypdf import PdfReader

from scripts.generate_synthetic_emails import generate, pdf_bytes


def test_pdf_fixture_has_a_real_text_layer():
    reader = PdfReader(io.BytesIO(pdf_bytes("Synthetic invoice INV-2048 payment approved")))
    assert len(reader.pages) == 1
    assert "INV-2048" in reader.pages[0].extract_text()


def test_generator_is_deterministic_and_golden_queries_match(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    a = generate(first, count=120, seed=42, documents=10)
    b = generate(second, count=120, seed=42, documents=10)
    assert a == b
    assert (first / "emails.mbox").read_bytes() == (second / "emails.mbox").read_bytes()
    for path in (first / "documents").iterdir():
        assert path.read_bytes() == (second / "documents" / path.name).read_bytes()
    golden = json.loads((first / "golden.json").read_text())
    with closing(mailbox.mbox(first / "emails.mbox", create=False)) as source:
        assert len(source) == golden["email_occurrences"] == 120
        bodies = [
            item.get_payload(0).get_payload(decode=True).decode()
            if item.is_multipart()
            else item.get_payload(decode=True).decode()
            for item in source
        ]
    for query, expected in golden["queries"].items():
        term = query.strip('"')
        assert sum(term.lower() in body.lower() for body in bodies) == expected
    assert golden["exact_duplicate_occurrences"] == 2
    for record in golden["document_manifest"]:
        assert (
            hashlib.sha256((first / "documents" / record["name"]).read_bytes()).hexdigest()
            == record["sha256"]
        )
    assert (first / "adversarial/traversal.zip").exists()
