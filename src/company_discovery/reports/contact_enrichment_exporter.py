from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from company_discovery.domain.contact_models import ContactEnrichmentSummary
from company_discovery.reports.workbook import update_contact_enrichment_workbook


class ContactEnrichmentArtifactExporter:
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
        self, payload: dict[str, Any], summary: ContactEnrichmentSummary
    ) -> dict[str, str]:
        run_dir = (
            self._artifacts_root
            / payload["source_discovery_run_id"]
            / "enrich"
            / payload["source_enrichment_run_id"]
            / "contacts"
            / payload["source_contact_run_id"]
            / "enrich"
            / payload["run_id"]
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            outcome: str((run_dir / f"{outcome}.csv").resolve())
            for outcome in ("ready", "review", "blocked")
        }
        paths["summary"] = str((run_dir / "summary.md").resolve())
        paths["json"] = str((run_dir / "run.json").resolve())
        for outcome in ("ready", "review", "blocked"):
            self._write_csv(Path(paths[outcome]), payload["items"], outcome)
        Path(paths["summary"]).write_text(self._markdown(payload, summary), encoding="utf-8")
        full_payload = dict(payload)
        full_payload["summary"] = summary.model_dump(mode="json")
        full_payload["status"] = "completed"
        paths["workbook"] = update_contact_enrichment_workbook(self._artifacts_root, full_payload)
        full_payload["artifacts"] = paths
        Path(paths["json"]).write_text(
            json.dumps(full_payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        return paths

    @classmethod
    def _write_csv(cls, path: Path, items: list[dict[str, Any]], outcome: str) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=cls.FIELDS)
            writer.writeheader()
            for item in items:
                if item["outcome"] != outcome:
                    continue
                discovery = item["discovery"]
                channels = item["channels"]
                writer.writerow(
                    {
                        "company_name": discovery["company_name"],
                        "company_domain": discovery["company_domain"],
                        "contact_name": discovery["contact_name"],
                        "title": discovery["title"],
                        "linkedin_url": discovery.get("linkedin_url") or "",
                        "email": channels.get("email") or "",
                        "phone": channels.get("phone") or "",
                        "status": outcome,
                        "notes": " | ".join(item.get("review_flags", [])),
                    }
                )

    @staticmethod
    def _markdown(payload: dict[str, Any], summary: ContactEnrichmentSummary) -> str:
        lines = [
            f"# Contact Enrichment Run {payload['run_id']}",
            "",
            f"- Contact discovery run: `{payload['source_contact_run_id']}`",
            f"- Contacts loaded: {summary.contacts_loaded}",
            f"- Fresh Apollo memory reused: {summary.memory_reused}",
            f"- Apollo people submitted: {summary.apollo_requests}",
            f"- Apollo batches: {summary.apollo_batches}",
            f"- Async polls: {summary.async_polls}",
            f"- Ready: {summary.ready}",
            f"- Review: {summary.review}",
            f"- Blocked: {summary.blocked}",
            "",
            "## People",
            "",
        ]
        for item in payload["items"]:
            lines.append(
                f"- **{item['discovery']['contact_name']}**, "
                f"{item['discovery']['title']} at {item['discovery']['company_name']}: "
                f"{item['outcome']}"
            )
        lines.append("")
        return "\n".join(lines)
