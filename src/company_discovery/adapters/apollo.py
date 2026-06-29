from __future__ import annotations

import time
from typing import Any

import httpx

from company_discovery.domain.contact_models import (
    ApolloBatchResult,
    ApolloPersonMatch,
    ApolloPersonRequest,
)
from company_discovery.services.normalization import canonical_domain
from company_discovery.settings import Settings


class ApolloClient:
    """Apollo people-enrichment adapter with bounded retry and async-result support."""

    MAX_BATCH_SIZE = 10

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.apollo_api_key:
            raise ValueError("APOLLO_API_KEY is required for contact enrichment")
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.apollo_base_url.rstrip("/"),
            headers={
                "X-Api-Key": settings.apollo_api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            timeout=settings.apollo_timeout_seconds,
        )
        self._pending_people: dict[str, list[ApolloPersonRequest]] = {}
        self._pending_matches: dict[str, list[ApolloPersonMatch]] = {}

    def enrich_people(
        self,
        people: list[ApolloPersonRequest],
        *,
        reveal_email: bool,
        reveal_phone: bool,
    ) -> ApolloBatchResult:
        if not people:
            return ApolloBatchResult()
        if len(people) > self.MAX_BATCH_SIZE:
            raise ValueError(f"Apollo bulk enrichment accepts at most {self.MAX_BATCH_SIZE} people")
        if reveal_phone and not self._settings.apollo_webhook_url:
            raise ValueError(
                "APOLLO_WEBHOOK_URL is required when phone enrichment is enabled; "
                "use --no-phone for synchronous email-only enrichment"
            )

        payload: dict[str, Any] = {
            "details": [self._person_payload(person) for person in people],
        }
        params: dict[str, Any] = {
            "reveal_personal_emails": False,
            "reveal_phone_number": reveal_phone,
            # Standard work email is synchronous. Waterfall email becomes useful only when
            # Apollo has a webhook destination for its asynchronous completion payload.
            "run_waterfall_email": reveal_email and bool(self._settings.apollo_webhook_url),
            "run_waterfall_phone": reveal_phone,
        }
        if self._settings.apollo_webhook_url:
            params["webhook_url"] = self._settings.apollo_webhook_url
        response = self._request(
            "POST", "/api/v1/people/bulk_match", json=payload, params=params
        )
        data = response.json()
        result = self._parse(data, people)
        if result.request_id:
            self._pending_people[result.request_id] = people
            self._pending_matches[result.request_id] = result.matches
        return result

    def poll(self, request_id: str) -> ApolloBatchResult:
        try:
            response = self._request("GET", f"/api/v1/webhook_result/{request_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return ApolloBatchResult(
                    matches=self._pending_matches.get(request_id, []),
                    request_id=request_id,
                    pending=True,
                )
            raise
        data = response.json()
        result = self._parse(data, self._pending_people.get(request_id, []))
        result = self._merge_pending_result(request_id, result)
        if not result.request_id:
            result = result.model_copy(update={"request_id": request_id})
        if not result.pending:
            self._pending_people.pop(request_id, None)
            self._pending_matches.pop(request_id, None)
        return result

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(3):
            response = self._client.request(method, path, **kwargs)
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                return response
            if attempt == 2:
                response.raise_for_status()
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after else float(2**attempt)
            time.sleep(delay)
        raise RuntimeError("Apollo request retry loop exited unexpectedly")

    @staticmethod
    def _person_payload(person: ApolloPersonRequest) -> dict[str, str]:
        payload = {
            "first_name": person.first_name,
            "last_name": person.last_name,
            "name": person.full_name,
            "organization_name": person.company_name,
            "domain": person.company_domain,
        }
        if person.linkedin_url:
            payload["linkedin_url"] = person.linkedin_url
        return payload

    @classmethod
    def _parse(
        cls, payload: dict[str, Any], requested: list[ApolloPersonRequest]
    ) -> ApolloBatchResult:
        source = cls._result_source(payload)
        request_id = cls._request_id(payload) or cls._request_id(source)
        status = str(
            payload.get("status")
            or payload.get("state")
            or source.get("status")
            or source.get("state")
            or ""
        ).lower()
        pending = status in {"pending", "processing", "queued", "running"}
        waterfall = source.get("waterfall") if isinstance(source.get("waterfall"), dict) else {}
        waterfall_status = str(waterfall.get("status") or "").lower()
        if request_id and waterfall_status in {
            "accepted",
            "partial_accepted",
            "pending",
            "processing",
            "queued",
            "running",
        }:
            pending = True
        records = source.get("matches") or source.get("people") or source.get("results") or []
        if isinstance(records, dict):
            records = records.get("matches") or records.get("people") or records.get("results") or []
        if not isinstance(records, list):
            records = []
        if request_id and not records and status not in {"complete", "completed", "success", "succeeded"}:
            pending = True

        matches: list[ApolloPersonMatch] = []
        for index, requested_person in enumerate(requested):
            raw = records[index] if index < len(records) and isinstance(records[index], dict) else {}
            person = raw.get("person") if isinstance(raw.get("person"), dict) else raw
            found = bool(person) and not bool(raw.get("error"))
            organization = person.get("organization") if isinstance(person.get("organization"), dict) else {}
            phones = cls._phones(person)
            email, email_status = cls._email(person)
            raw_domain = (
                organization.get("primary_domain")
                or organization.get("website_url")
                or person.get("organization_domain")
            )
            matches.append(
                ApolloPersonMatch(
                    candidate_id=requested_person.candidate_id,
                    person_found=found,
                    full_name=person.get("name") or cls._joined_name(person),
                    linkedin_url=person.get("linkedin_url"),
                    title=person.get("title"),
                    organization_name=organization.get("name") or person.get("organization_name"),
                    organization_domain=canonical_domain(str(raw_domain)) if raw_domain else None,
                    email=email,
                    email_status=email_status,
                    phones=phones,
                    apollo_person_id=person.get("id"),
                    raw=raw,
                )
            )
        return ApolloBatchResult(matches=matches, request_id=request_id, pending=pending)

    @staticmethod
    def _result_source(payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(source.get("webhook_result"), dict):
            return source["webhook_result"]
        return source

    def _merge_pending_result(
        self, request_id: str, result: ApolloBatchResult
    ) -> ApolloBatchResult:
        initial = self._by_candidate_id(self._pending_matches.get(request_id, []))
        if not initial:
            return result
        merged = [
            self._merge_match(initial.get(match.candidate_id), match)
            for match in result.matches
        ]
        returned_ids = {match.candidate_id for match in merged}
        merged.extend(
            match for candidate_id, match in initial.items() if candidate_id not in returned_ids
        )
        return result.model_copy(update={"matches": merged})

    @staticmethod
    def _by_candidate_id(matches: list[ApolloPersonMatch]) -> dict[int, ApolloPersonMatch]:
        return {match.candidate_id: match for match in matches}

    @staticmethod
    def _merge_match(
        initial: ApolloPersonMatch | None, latest: ApolloPersonMatch
    ) -> ApolloPersonMatch:
        if initial is None:
            return latest
        phones = list(dict.fromkeys([*initial.phones, *latest.phones]))
        raw: dict[str, Any] = {"initial": initial.raw}
        if latest.raw:
            raw["async"] = latest.raw
        return initial.model_copy(
            update={
                "person_found": initial.person_found or latest.person_found,
                "full_name": latest.full_name or initial.full_name,
                "linkedin_url": latest.linkedin_url or initial.linkedin_url,
                "title": latest.title or initial.title,
                "organization_name": latest.organization_name or initial.organization_name,
                "organization_domain": latest.organization_domain or initial.organization_domain,
                "email": latest.email or initial.email,
                "email_status": latest.email_status or initial.email_status,
                "phones": phones,
                "apollo_person_id": latest.apollo_person_id or initial.apollo_person_id,
                "raw": raw,
            }
        )

    @staticmethod
    def _request_id(payload: dict[str, Any]) -> str | None:
        direct = payload.get("request_id") or payload.get("requestId")
        if direct:
            return str(direct)
        data = payload.get("data")
        if isinstance(data, dict):
            nested = data.get("request_id") or data.get("requestId")
            return str(nested) if nested else None
        return None

    @staticmethod
    def _joined_name(person: dict[str, Any]) -> str | None:
        name = " ".join(
            part for part in (person.get("first_name"), person.get("last_name")) if part
        )
        return name or None

    @staticmethod
    def _email(person: dict[str, Any]) -> tuple[str | None, str | None]:
        email = person.get("email")
        status = person.get("email_status") or person.get("email_status_cd")
        if isinstance(email, str) and email and not email.startswith("email_not_unlocked@"):
            return email, str(status) if status else None
        for item in person.get("emails") or []:
            if not isinstance(item, dict):
                continue
            candidate = item.get("email")
            if not candidate or str(candidate).startswith("email_not_unlocked@"):
                continue
            item_status = item.get("email_status") or item.get("email_status_cd") or item.get("status")
            return str(candidate), str(item_status) if item_status else None
        return None, str(status) if status else None

    @staticmethod
    def _phones(person: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for phone in person.get("phone_numbers") or []:
            if not isinstance(phone, dict):
                continue
            value = phone.get("sanitized_number") or phone.get("raw_number") or phone.get("number")
            if value and value not in values:
                values.append(str(value))
        direct = person.get("phone") or person.get("mobile_phone") or person.get("sanitized_phone")
        if direct and str(direct) not in values:
            values.append(str(direct))
        return values

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
