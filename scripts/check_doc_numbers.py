"""Verify current documentation counts against fresh local execution.

This gate intentionally validates current summary claims, not dated historical
measurements inside ADR bodies. ADRs keep their original record and expose a
separate current-verification addendum that is checked here.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

from custos.chunker import chunk_document
from custos.ingest import CORPUS_DIR, load_manifest

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Measurements:
    pytest_passed: int
    eval_proven: int
    eval_skipped: int
    suite_cases: dict[str, int]
    corpus_chunks: int
    corpus_documents: int


@dataclass(frozen=True)
class Claim:
    path: str
    pattern: Pattern[str]
    measurement: str
    description: str


CURRENT_CLAIMS = [
    Claim(
        "CLAUDE.md",
        re.compile(r"\b(?P<value>\d+) pytest\b"),
        "pytest_passed",
        "passing pytest cases",
    ),
    Claim(
        "CLAUDE.md",
        re.compile(r"ALL PROVEN`? \((?P<value>\d+)/\d+\)"),
        "eval_proven",
        "deterministic evals proven with Qdrant",
    ),
    Claim(
        "docs/SECURITY.md",
        re.compile(r"\*\*(?P<value>\d+) deterministic security evals\*\*"),
        "eval_proven",
        "deterministic security evals",
    ),
    Claim(
        "THREAT_MODEL.md",
        re.compile(r"injection\.py` \((?P<value>\d+) cases\)"),
        "suite:injection",
        "injection suite cases",
    ),
    Claim(
        "THREAT_MODEL.md",
        re.compile(r"\| T1 \(direct injection\).*\| (?P<value>\d+) \|"),
        "suite:injection",
        "T1 summary-table cases",
    ),
    Claim(
        "docs/RED_TEAM.md",
        re.compile(r"injection\.py`, (?P<value>\d+)/\d+ PASS"),
        "suite:injection",
        "red-team injection cases",
    ),
    Claim(
        "docs/RED_TEAM.md",
        re.compile(
            r"(?P<chunks>\d+) chunks across (?P<documents>\d+) documents"
        ),
        "corpus_pair",
        "red-team corpus size",
    ),
    Claim(
        "docs/decisions/001-vector-store.md",
        re.compile(
            r"(?P<chunks>\d+)-chunk/(?P<documents>\d+)-document demo corpus"
        ),
        "corpus_pair",
        "ADR-001 corpus size",
    ),
    Claim(
        "docs/decisions/006-agent-runtime.md",
        re.compile(r"CURRENT_PYTEST_COUNT=(?P<value>\d+)"),
        "pytest_passed",
        "ADR-006 current verification addendum",
    ),
]

SCAN_PATHS = [
    "README.md",
    "CLAUDE.md",
    "THREAT_MODEL.md",
    "docs/SECURITY.md",
    "docs/RED_TEAM.md",
]

FORBIDDEN_CURRENT_CLAIMS = [
    (re.compile(r"\b55 security tests\b", re.IGNORECASE), "eval_proven"),
    (re.compile(r"\b199 pytest\b", re.IGNORECASE), "pytest_passed"),
]


def _run(command: list[str]) -> str:
    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["CUSTOS_VECTOR_BACKEND"] = "qdrant"
    env["CUSTOS_AGENT_RUNTIME"] = "native"
    env.pop("ANTHROPIC_API_KEY", None)
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(output, file=sys.stderr)
        raise RuntimeError(
            f"Command failed with exit {result.returncode}: {' '.join(command)}"
        )
    return output


def _measure() -> Measurements:
    pytest_output = _run([sys.executable, "-m", "pytest", "-q"])
    pytest_match = re.search(r"(?P<passed>\d+) passed", pytest_output)
    if pytest_match is None:
        raise RuntimeError("Could not parse pytest pass count")

    _run([sys.executable, "-m", "custos.ingest"])
    eval_output = _run([sys.executable, "-m", "evals.harness"])
    eval_match = re.search(
        r"Proven:\s*(?P<proven>\d+)\s+Skipped:\s*(?P<skipped>\d+)"
        r"\s+Failed:\s*(?P<failed>\d+)",
        eval_output,
    )
    if eval_match is None:
        raise RuntimeError("Could not parse eval summary")
    if int(eval_match.group("failed")) != 0:
        raise RuntimeError("Eval harness reported failures")

    suite_cases = {
        match.group("suite"): int(match.group("cases"))
        for match in re.finditer(
            r"Running: evals\.suites\.(?P<suite>\w+) \((?P<cases>\d+) cases\)",
            eval_output,
        )
    }
    if "injection" not in suite_cases:
        raise RuntimeError("Could not parse injection suite case count")

    documents = load_manifest(CORPUS_DIR)
    corpus_chunks = 0
    for metadata in documents:
        text = (CORPUS_DIR / str(metadata["file"])).read_text(encoding="utf-8")
        permissions_value = metadata.get("permissions", [])
        permissions = (
            [str(value) for value in permissions_value]
            if isinstance(permissions_value, list)
            else []
        )
        corpus_chunks += len(
            chunk_document(
                text=text,
                doc_id=str(metadata["doc_id"]),
                permissions=permissions,
            )
        )

    return Measurements(
        pytest_passed=int(pytest_match.group("passed")),
        eval_proven=int(eval_match.group("proven")),
        eval_skipped=int(eval_match.group("skipped")),
        suite_cases=suite_cases,
        corpus_chunks=corpus_chunks,
        corpus_documents=len(documents),
    )


def _expected(measurements: Measurements, key: str) -> int:
    if key.startswith("suite:"):
        return measurements.suite_cases[key.removeprefix("suite:")]
    return int(getattr(measurements, key))


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _validate_claims(measurements: Measurements) -> list[str]:
    failures: list[str] = []
    for claim in CURRENT_CLAIMS:
        text = (ROOT / claim.path).read_text(encoding="utf-8")
        matches = list(claim.pattern.finditer(text))
        if not matches:
            failures.append(
                f"{claim.path}: missing current numeric claim for {claim.description}"
            )
            continue
        for match in matches:
            line = _line_number(text, match.start())
            if claim.measurement == "corpus_pair":
                stated_chunks = int(match.group("chunks"))
                stated_documents = int(match.group("documents"))
                if (
                    stated_chunks != measurements.corpus_chunks
                    or stated_documents != measurements.corpus_documents
                ):
                    failures.append(
                        f"{claim.path}:{line}: stated "
                        f"{stated_chunks} chunks/{stated_documents} documents; real "
                        f"{measurements.corpus_chunks} chunks/"
                        f"{measurements.corpus_documents} documents"
                    )
                continue

            stated = int(match.group("value"))
            real = _expected(measurements, claim.measurement)
            if stated != real:
                failures.append(
                    f"{claim.path}:{line}: stated {stated}; real {real} "
                    f"({claim.description})"
                )

    decision_paths = sorted((ROOT / "docs" / "decisions").glob("*.md"))
    for path in [*(ROOT / item for item in SCAN_PATHS), *decision_paths]:
        text = path.read_text(encoding="utf-8")
        for pattern, measurement in FORBIDDEN_CURRENT_CLAIMS:
            for match in pattern.finditer(text):
                line = _line_number(text, match.start())
                stated_match = re.search(r"\d+", match.group(0))
                stated = int(stated_match.group(0)) if stated_match else -1
                failures.append(
                    f"{path.relative_to(ROOT)}:{line}: stated {stated}; real "
                    f"{_expected(measurements, measurement)} (stale current claim)"
                )
    return failures


def main() -> int:
    try:
        measurements = _measure()
    except RuntimeError as error:
        print(f"DOC NUMBERS ERROR: {error}", file=sys.stderr)
        return 1

    failures = _validate_claims(measurements)
    if failures:
        print("DOC NUMBER GATE FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        "DOC NUMBERS OK: "
        f"pytest={measurements.pytest_passed}, "
        f"evals={measurements.eval_proven} proven/"
        f"{measurements.eval_skipped} skipped, "
        f"injection={measurements.suite_cases['injection']}, "
        f"corpus={measurements.corpus_chunks} chunks/"
        f"{measurements.corpus_documents} documents"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
