from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from company_discovery.domain.models import RunSummary
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.reports.workbook import update_company_discovery_workbook


class ArtifactExporter:
    def __init__(self, artifacts_root: Path) -> None:
        self._artifacts_root = artifacts_root

    def export(self, run_payload: dict[str, Any], summary: RunSummary) -> dict[str, str]:
        run_id = run_payload["run_id"]
        run_dir = self._artifacts_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {
            bucket: str((run_dir / f"{bucket}.csv").resolve())
            for bucket in ("selected", "reserve", "rejected")
        }
        paths["summary"] = str((run_dir / "summary.md").resolve())
        paths["json"] = str((run_dir / "run.json").resolve())
        for bucket in ("selected", "reserve", "rejected"):
            path = Path(paths[bucket])
            self._write_csv(path, run_payload["candidates"], bucket)

        report_path = Path(paths["summary"])
        report_path.write_text(self._markdown(run_payload, summary), encoding="utf-8")

        json_path = Path(paths["json"])
        full_payload = dict(run_payload)
        full_payload["summary"] = summary.model_dump(mode="json")
        paths["workbook"] = update_company_discovery_workbook(self._artifacts_root, full_payload)
        full_payload["artifacts"] = paths
        json_path.write_text(json.dumps(full_payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return paths

    @staticmethod
    def _write_csv(path: Path, candidates: list[dict[str, Any]], bucket: str) -> None:
        rows = [item for item in candidates if item["bucket"] == bucket]
        fieldnames = [
            "company_name",
            "domain",
            "vertical",
            "target_vertical",
            "country",
            "state",
            "employee_min",
            "employee_max",
            "ownership_type",
            "fit",
            "reason",
            "reason_codes",
            "evidence",
            "source",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for item in rows:
                company = item["company"]
                evaluation = item["evaluation"]
                writer.writerow(
                    {
                        "company_name": company["company_name"],
                        "domain": company["domain"],
                        "vertical": company.get("vertical") or "",
                        "target_vertical": evaluation.get("target_vertical") or "",
                        "country": company.get("country") or "",
                        "state": company.get("state") or "",
                        "employee_min": company.get("employee_min") or "",
                        "employee_max": company.get("employee_max") or "",
                        "ownership_type": company.get("ownership_type") or "",
                        "fit": evaluation["fit"],
                        "reason": evaluation["reason"],
                        "reason_codes": "; ".join(evaluation.get("reason_codes", [])),
                        "evidence": " | ".join(evaluation.get("evidence", [])),
                        "source": item["source"],
                    }
                )

    @staticmethod
    def _markdown(run_payload: dict[str, Any], summary: RunSummary) -> str:
        spec = run_payload["spec"]
        lines = [
            f"# Company Discovery Run {run_payload['run_id']}",
            "",
            f"- Status: {run_payload['status']}",
            "- Verticals: "
            + ", ".join(
                f"{vertical['label']} (`{vertical['key']}`)"
                for vertical in spec["verticals"]
            ),
            f"- Balance mode: {spec.get('balance_mode', 'soft')}",
            f"- Country: {spec['geography']['country']}",
            f"- States: {', '.join(spec['geography']['states']) or 'all'}",
            f"- Requested: {spec['count']}",
            "",
            "## Results",
            "",
            f"- Memory matched: {summary.memory_matched}",
            f"- Memory reused: {summary.memory_reused}",
            f"- External gap: {summary.external_gap}",
            f"- Queries generated: {summary.queries_generated}",
            f"- Raw results: {summary.raw_results}",
            f"- Unique candidates: {summary.unique_candidates}",
            f"- Selected: {summary.selected}",
            f"- Reserve: {summary.reserve}",
            f"- Rejected: {summary.rejected}",
            "",
        ]
        normalized_spec = CompanySearchSpec.model_validate(spec)
        if normalized_spec.missing_constraints:
            lines.extend(
                ["## Open Modes", ""]
                + [f"- {condition}" for condition in normalized_spec.missing_constraints]
                + [""]
            )
        for bucket in ("selected", "reserve", "rejected"):
            title = bucket.title()
            lines.extend([f"## {title}", ""])
            items = [item for item in run_payload["candidates"] if item["bucket"] == bucket]
            if not items:
                lines.extend(["None.", ""])
                continue
            for item in items:
                company = item["company"]
                evaluation = item["evaluation"]
                lines.append(
                    f"- **{company['company_name']}** ({company['domain']}): {evaluation['reason']}"
                )
            lines.append("")
        return "\n".join(lines)
