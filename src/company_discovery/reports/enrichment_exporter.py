from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from company_discovery.domain.models import EnrichmentSummary


class EnrichmentArtifactExporter:
    FIELDS = [
        "company_name",
        "domain",
        "phone",
        "street_address",
        "city",
        "state",
        "zip",
        "vertical",
        "employee_min",
        "employee_max",
        "ownership_type",
        "independence_status",
        "outcome",
    ]

    def __init__(self, artifacts_root: Path) -> None:
        self._artifacts_root = artifacts_root

    def export(self, payload: dict[str, Any], summary: EnrichmentSummary) -> dict[str, str]:
        run_dir = self._artifacts_root / payload["discovery_run_id"] / "enrichment" / payload["run_id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "enriched": str((run_dir / "enriched.csv").resolve()),
            "review": str((run_dir / "review.csv").resolve()),
            "blocked": str((run_dir / "blocked.csv").resolve()),
            "summary": str((run_dir / "summary.md").resolve()),
            "json": str((run_dir / "run.json").resolve()),
        }
        self._write_csv(Path(paths["enriched"]), payload["items"], {"enriched_ready"})
        self._write_csv(
            Path(paths["review"]),
            payload["items"],
            {"independence_unconfirmed", "enriched_with_gaps"},
        )
        self._write_csv(
            Path(paths["blocked"]),
            payload["items"],
            {"identity_conflict", "geography_conflict", "fit_conflict", "enrichment_failed"},
        )
        Path(paths["summary"]).write_text(self._markdown(payload, summary), encoding="utf-8")
        full_payload = dict(payload)
        full_payload["summary"] = summary.model_dump(mode="json")
        full_payload["artifacts"] = paths
        Path(paths["json"]).write_text(
            json.dumps(full_payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        return paths

    @classmethod
    def _write_csv(cls, path: Path, items: list[dict[str, Any]], outcomes: set[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=cls.FIELDS)
            writer.writeheader()
            for item in items:
                if item["outcome"] not in outcomes:
                    continue
                discovery = item["discovery"]
                enrichment = item["enrichment"]
                phone = enrichment.get("phone") or {}
                location = enrichment.get("location") or {}
                independence = enrichment.get("independence") or {}
                writer.writerow(
                    {
                        "company_name": discovery["company_name"],
                        "domain": discovery["domain"],
                        "phone": phone.get("display_value", ""),
                        "street_address": location.get("street_address", ""),
                        "city": location.get("city", ""),
                        "state": location.get("state") or discovery.get("state") or "",
                        "zip": location.get("zip", ""),
                        "vertical": discovery.get("target_vertical") or discovery.get("vertical") or "",
                        "employee_min": discovery.get("employee_min") or "",
                        "employee_max": discovery.get("employee_max") or "",
                        "ownership_type": discovery.get("ownership_type") or "",
                        "independence_status": independence.get("status", "unknown"),
                        "outcome": item["outcome"],
                    }
                )

    @staticmethod
    def _markdown(payload: dict[str, Any], summary: EnrichmentSummary) -> str:
        lines = [
            f"# Company Enrichment Run {payload['run_id']}",
            "",
            f"- Discovery run: `{payload['discovery_run_id']}`",
            f"- Input bucket: {payload['bucket']}",
            f"- Processed: {summary.processed}",
            f"- Discovery facts inherited: {summary.inherited_facts}",
            f"- Memory profiles reused: {summary.memory_profiles_reused}",
            f"- Websites fetched: {summary.websites_fetched}",
            f"- Fallback searches: {summary.fallback_searches}",
            f"- Ready: {summary.ready}",
            f"- Review: {summary.review}",
            f"- Blocked: {summary.blocked}",
            f"- Failed: {summary.failed}",
            "",
            "## Companies",
            "",
        ]
        for item in payload["items"]:
            lines.append(
                f"- **{item['discovery']['company_name']}** ({item['discovery']['domain']}): "
                f"{item['outcome']}"
            )
        lines.append("")
        return "\n".join(lines)
