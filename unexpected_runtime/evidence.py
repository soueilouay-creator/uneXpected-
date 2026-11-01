from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any


EVIDENCE_KINDS = frozenset({"artifact", "test", "source", "measurement"})


class EvidenceContractError(ValueError):
    """Raised when an acceptance contract or evidence checker violates its schema."""


EvidenceChecker = Callable[[Any, dict[str, Any], dict[str, Any]], dict[str, Any]]


class EvidenceEngine:
    """Deterministic evidence collector and fail-closed acceptance gate.

    Checkers are trusted host adapters. Candidate text and model-authored claims
    are never treated as evidence by themselves. Every passing record must carry
    an actual measurement and a provenance reference and is bound to the exact
    candidate fingerprint that was checked.
    """

    def __init__(self, checkers: Mapping[str, EvidenceChecker] | None = None) -> None:
        supplied = dict(checkers or {})
        unknown = set(supplied) - EVIDENCE_KINDS
        if unknown:
            raise EvidenceContractError(
                "Unknown evidence checker kind(s): " + ", ".join(sorted(unknown))
            )
        if "artifact" in supplied:
            raise EvidenceContractError("The built-in artifact checker cannot be replaced.")
        for kind, checker in supplied.items():
            if not callable(checker):
                raise EvidenceContractError(f"The {kind} evidence checker must be callable.")
        self.checkers: dict[str, EvidenceChecker] = {
            "artifact": self._check_artifact,
            **supplied,
        }

    @staticmethod
    def fingerprint(candidate: Any) -> str:
        try:
            canonical = json.dumps(
                candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise EvidenceContractError("Candidate must be finite JSON-serializable data.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def validate_criteria(criteria: Any) -> list[dict[str, Any]]:
        if not isinstance(criteria, list) or not criteria:
            raise EvidenceContractError("At least one acceptance criterion is required.")
        if len(criteria) > 50:
            raise EvidenceContractError("At most 50 acceptance criteria are allowed.")

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(criteria):
            if not isinstance(item, dict):
                raise EvidenceContractError(f"Criterion {index + 1} must be an object.")
            criterion_id = item.get("id")
            description = item.get("description")
            kind = item.get("kind")
            target = item.get("target")
            required = item.get("required")
            if not isinstance(criterion_id, str) or not criterion_id.strip() or len(criterion_id) > 64:
                raise EvidenceContractError(f"Criterion {index + 1} requires a non-empty id of at most 64 characters.")
            criterion_id = criterion_id.strip()
            if criterion_id in seen:
                raise EvidenceContractError(f"Duplicate criterion id: {criterion_id}.")
            seen.add(criterion_id)
            if not isinstance(description, str) or not description.strip():
                raise EvidenceContractError(f"Criterion {criterion_id} requires a description.")
            if kind not in EVIDENCE_KINDS:
                raise EvidenceContractError(
                    f"Criterion {criterion_id} has unsupported kind; expected one of {sorted(EVIDENCE_KINDS)}."
                )
            if not isinstance(target, str) or not target.strip():
                raise EvidenceContractError(f"Criterion {criterion_id} requires a measurable target.")
            if type(required) is not bool:
                raise EvidenceContractError(f"Criterion {criterion_id} requires a boolean required field.")
            normalized.append({
                "id": criterion_id,
                "description": description.strip(),
                "kind": kind,
                "target": target.strip(),
                "required": required,
            })
        if not any(item["required"] for item in normalized):
            raise EvidenceContractError("At least one acceptance criterion must be required.")
        return normalized

    @staticmethod
    def _check_artifact(candidate: Any, criterion: dict[str, Any],
                        context: dict[str, Any]) -> dict[str, Any]:
        non_empty = isinstance(candidate, str) and bool(candidate.strip())
        return {
            "passed": non_empty,
            "actual": {"character_count": len(candidate)} if isinstance(candidate, str) else None,
            "expected": criterion["target"],
            "evidence_ref": "runtime://candidate-sha256/" + EvidenceEngine.fingerprint(candidate),
            "details": "Candidate non-empty integrity check.",
        }

    def evaluate(self, candidate: Any, criteria: Any,
                 context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        contract = self.validate_criteria(criteria)
        if context is not None and not isinstance(context, Mapping):
            raise EvidenceContractError("Evidence context must be a mapping.")
        fingerprint = self.fingerprint(candidate)
        safe_context = dict(context or {})
        records: list[dict[str, Any]] = []

        for criterion in contract:
            checker = self.checkers.get(criterion["kind"])
            if checker is None:
                records.append({
                    "criterion_id": criterion["id"],
                    "kind": criterion["kind"],
                    "required": criterion["required"],
                    "status": "unverified",
                    "candidate_sha256": fingerprint,
                    "missing_fields": ["trusted_checker"],
                    "details": f"No trusted {criterion['kind']} evidence checker is configured.",
                })
                continue

            try:
                raw = checker(candidate, dict(criterion), safe_context)
            except Exception as exc:
                records.append({
                    "criterion_id": criterion["id"],
                    "kind": criterion["kind"],
                    "required": criterion["required"],
                    "status": "failed",
                    "candidate_sha256": fingerprint,
                    "missing_fields": [],
                    "details": f"Evidence checker failed: {type(exc).__name__}.",
                })
                continue

            if not isinstance(raw, dict) or type(raw.get("passed")) is not bool:
                records.append({
                    "criterion_id": criterion["id"],
                    "kind": criterion["kind"],
                    "required": criterion["required"],
                    "status": "unverified",
                    "candidate_sha256": fingerprint,
                    "missing_fields": ["boolean passed", "actual", "evidence_ref"],
                    "details": "Evidence checker returned an invalid result.",
                })
                continue

            missing = []
            if "actual" not in raw or raw.get("actual") is None:
                missing.append("actual")
            evidence_ref = raw.get("evidence_ref")
            if not isinstance(evidence_ref, str) or not evidence_ref.strip():
                missing.append("evidence_ref")
            if missing:
                status = "unverified"
            else:
                status = "passed" if raw["passed"] else "failed"

            records.append({
                "criterion_id": criterion["id"],
                "kind": criterion["kind"],
                "required": criterion["required"],
                "status": status,
                "passed": status == "passed",
                "expected": raw.get("expected", criterion["target"]),
                "actual": raw.get("actual"),
                "evidence_ref": evidence_ref if isinstance(evidence_ref, str) else None,
                "candidate_sha256": fingerprint,
                "missing_fields": missing,
                "details": str(raw.get("details") or ""),
            })

        blockers = [
            item["criterion_id"] for item in records
            if item["required"] and item["status"] != "passed"
        ]
        required_total = sum(1 for item in contract if item["required"])
        required_passed = required_total - len(blockers)
        return {
            "schema_version": "1.0",
            "passed": not blockers,
            "candidate_sha256": fingerprint,
            "criteria_total": len(contract),
            "required_total": required_total,
            "required_passed": required_passed,
            "failed_criteria": blockers,
            "evidence": records,
            "summary": (
                f"{required_passed}/{required_total} required criteria have verified evidence."
                if not blockers else
                f"Evidence gate blocked: {', '.join(blockers)}."
            ),
        }

    @staticmethod
    def is_current(report: Any, candidate: Any) -> bool:
        if not isinstance(report, dict) or report.get("schema_version") != "1.0":
            return False
        if report.get("passed") is not True:
            return False
        try:
            fingerprint = EvidenceEngine.fingerprint(candidate)
        except EvidenceContractError:
            return False
        if report.get("candidate_sha256") != fingerprint:
            return False
        evidence = report.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return False
        required_total = report.get("required_total")
        required_passed = report.get("required_passed")
        if (isinstance(required_total, bool) or not isinstance(required_total, int)
                or required_total < 1 or required_passed != required_total
                or report.get("failed_criteria") != []):
            return False
        required_records = [item for item in evidence if isinstance(item, dict) and item.get("required") is True]
        if len(required_records) != required_total:
            return False
        return all(
            item.get("status") == "passed"
            and item.get("candidate_sha256") == fingerprint
            and isinstance(item.get("evidence_ref"), str)
            and bool(item.get("evidence_ref").strip())
            and item.get("actual") is not None
            for item in required_records
        )
