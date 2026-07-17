"""Tests for the demo corpus generator.

Verifies byte-reproducibility, reserved-range PII, manifest integrity,
and injection payload presence.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

CORPUS_DIR = Path(__file__).parent.parent / "corpus" / "output"
GENERATE_SCRIPT = Path(__file__).parent.parent / "corpus" / "generate.py"


def _generate_corpus() -> None:
    """Run the corpus generator."""
    subprocess.check_call(
        [sys.executable, str(GENERATE_SCRIPT)],
        env={
            "PATH": "",
            "CORPUS_SEED": "42",
            "CORPUS_REFERENCE_DATE": "2026-07-17",
        },
    )


def _load_manifest() -> dict:
    manifest_path = CORPUS_DIR / "manifest.yaml"
    with open(manifest_path) as f:
        return yaml.safe_load(f)


class TestCorpusReproducibility:
    """The corpus must be byte-identical across runs."""

    @classmethod
    def setup_class(cls) -> None:
        _generate_corpus()
        cls.manifest = _load_manifest()
        cls.checksums_first_run = {
            doc["file"]: doc["sha256"] for doc in cls.manifest["documents"]
        }
        # Run a second time
        _generate_corpus()
        cls.manifest_second = _load_manifest()
        cls.checksums_second_run = {
            doc["file"]: doc["sha256"] for doc in cls.manifest_second["documents"]
        }

    def test_same_file_count(self) -> None:
        assert len(self.checksums_first_run) == len(self.checksums_second_run)

    def test_checksums_match(self) -> None:
        for file_name, checksum in self.checksums_first_run.items():
            assert checksum == self.checksums_second_run[file_name], (
                f"{file_name} checksum differs between runs"
            )

    def test_checksums_are_valid(self) -> None:
        for doc in self.manifest["documents"]:
            file_path = CORPUS_DIR / doc["file"]
            actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
            assert actual == doc["sha256"], f"{doc['file']} checksum mismatch"


class TestReservedRangePII:
    """All PII must use reserved/invalid ranges."""

    @classmethod
    def setup_class(cls) -> None:
        _generate_corpus()
        cls.hr_content = (CORPUS_DIR / "hr-001.md").read_text()

    def test_emails_use_reserved_domains(self) -> None:
        import re
        emails = re.findall(r"[\w.]+@[\w.]+", self.hr_content)
        for email in emails:
            domain = email.split("@")[1]
            assert domain in ("example.com", "example.org"), (
                f"Email {email} uses non-reserved domain {domain}"
            )

    def test_phones_use_555_range(self) -> None:
        import re
        phones = re.findall(r"\(555\) 555-0\d{3}", self.hr_content)
        assert len(phones) > 0, "No 555 phone numbers found in HR records"
        for phone in phones:
            suffix = int(phone[-3:])
            assert 100 <= suffix <= 199, f"Phone {phone} outside 555-0100 to 555-0199 range"

    def test_ssns_use_never_issued_area(self) -> None:
        import re
        ssns = re.findall(r"\d{3}-\d{2}-\d{4}", self.hr_content)
        assert len(ssns) > 0, "No SSNs found in HR records"
        for ssn in ssns:
            area = int(ssn.split("-")[0])
            assert area >= 900, f"SSN {ssn} uses area {area}, which could be a real SSN"


class TestManifestIntegrity:
    """The manifest must correctly describe the corpus."""

    @classmethod
    def setup_class(cls) -> None:
        _generate_corpus()
        cls.manifest = _load_manifest()

    def test_pii_notice_present(self) -> None:
        assert "pii_notice" in self.manifest
        assert "reserved" in self.manifest["pii_notice"].lower()

    def test_all_files_exist(self) -> None:
        for doc in self.manifest["documents"]:
            file_path = CORPUS_DIR / doc["file"]
            assert file_path.exists(), f"Manifest lists {doc['file']} but file does not exist"

    def test_permissions_are_set(self) -> None:
        for doc in self.manifest["documents"]:
            assert "permissions" in doc, f"{doc['doc_id']} missing permissions"
            assert len(doc["permissions"]) > 0

    def test_restricted_docs_exist(self) -> None:
        restricted = [d for d in self.manifest["documents"] if "general" not in d["permissions"]]
        assert len(restricted) >= 2, "Need at least 2 restricted docs (HR + finance)"

    def test_payload_docs_exist(self) -> None:
        payloads = [d for d in self.manifest["documents"] if d.get("has_payload")]
        assert len(payloads) >= 3, "Need at least 3 injection payload docs"

    def test_payload_descriptions_present(self) -> None:
        for doc in self.manifest["documents"]:
            if doc.get("has_payload"):
                assert "payload_type" in doc, f"{doc['doc_id']} missing payload_type"
                assert "payload_description" in doc, f"{doc['doc_id']} missing payload_description"

    def test_document_count(self) -> None:
        docs = self.manifest["documents"]
        assert len(docs) == 9, f"Expected 9 documents, got {len(docs)}"
