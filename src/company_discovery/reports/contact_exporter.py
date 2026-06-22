from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from company_discovery.domain.contact_models import ContactDiscoverySummary


class ContactDiscoveryArtifactExporter:
    FIELDS = [
        "company_name",
        "company_domain",
        "contact_name",
        "title",
        "linkedin_url",
        "email",
        "phone",
        "status",
        "notes",
    ]

    def __init__(self, artifacts_root: Path) -> None:
        self._artifacts_root = artifacts_root

    def export(
        self, payload: dict[str, Any], summary: ContactDiscoverySummary
    ) -> dict[str, str]:
        run_dir = (
            self._artifacts_root
            / payload["source_discovery_run_id"]
            / "enrichment"
            / payload["source_enrichment_run_id"]
            / "contacts"
            / payload["run_id"]
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "accepted": str((run_dir / "accepted.csv").resolve()),
            "review": str((run_dir / "review.csv").resolve()),
            "rejected": str((run_dir / "rejected.csv").resolve()),
            "summary": str((run_dir / "summary.md").resolve()),
            "json": str((run_dir / "run.json").resolve()),
        }
        for verdict in ("accepted", "review", "rejected"):
            self._write_csv(Path(paths[verdict]), payload["items"], verdict)
        Path(paths["summary"]).write_text(
            self._markdown(payload, summary), encoding="utf-8"
        )
        full_payload = dict(payload)
        full_payload["summary"] = summary.model_dump(mode="json")
        full_payload["status"] = "completed"
        full_payload["artifacts"] = paths
        Path(paths["json"]).write_text(
            json.dumps(full_payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        return paths

    @classmethod
    def _write_csv(
        cls, path: Path, items: list[dict[str, Any]], verdict: str
    ) -> None:
        seen: set[int] = set()
        verdict_rank = {"rejected": 0, "review": 1, "accepted": 2}
        best_verdict: dict[int, str] = {}
        for item in items:
            candidate_id = item["candidate_id"]
            current = best_verdict.get(candidate_id, "rejected")
            if verdict_rank[item["verdict"]] >= verdict_rank[current]:
                best_verdict[candidate_id] = item["verdict"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=cls.FIELDS)
            writer.writeheader()
            for item in items:
                if (
                    item["verdict"] != verdict
                    or best_verdict[item["candidate_id"]] != verdict
                    or item["candidate_id"] in seen
                ):
                    continue
                seen.add(item["candidate_id"])
                candidate = item["candidate"]
                related = [
                    other
                    for other in items
                    if other["candidate_id"] == item["candidate_id"]
                    and other["verdict"] == verdict
                ]
                roles = ", ".join(dict.fromkeys(other["role_key"] for other in related))
                reasons = " | ".join(dict.fromkeys(other["reason"] for other in related))
                writer.writerow(
                    {
                        "company_name": candidate["company_name"],
                        "company_domain": candidate["company_domain"],
                        "contact_name": candidate["full_name"],
                        "title": candidate["title"],
                        "linkedin_url": candidate.get("linkedin_url") or "",
                        "email": "",
                        "phone": "",
                        "status": verdict,
                        "notes": f"{roles}: {reasons}",
                    }
                )

    @staticmethod
    def _markdown(payload: dict[str, Any], summary: ContactDiscoverySummary) -> str:
        lines = [
            f"# Contact Discovery Run {payload['run_id']}",
            "",
            f"- Company enrichment run: `{payload['source_enrichment_run_id']}`",
            f"- Companies loaded: {summary.companies_loaded}",
            f"- Contacts reused from memory: {summary.memory_reused}",
            f"- Role gaps sent to live search: {summary.role_gaps}",
            f"- Exa queries: {summary.queries_run}",
            f"- Raw results: {summary.raw_results}",
            f"- Unique people: {summary.unique_people}",
            f"- Accepted: {summary.accepted}",
            f"- Review: {summary.review}",
            f"- Rejected: {summary.rejected}",
            "",
            "## People",
            "",
        ]
        for item in payload["items"]:
            candidate = item["candidate"]
            lines.append(
                f"- **{candidate['full_name']}**, {candidate['title']} at "
                f"{candidate['company_name']}: {item['verdict']} ({item['role_key']})"
            )
        lines.append("")
        return "\n".join(lines)
