from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from company_discovery.domain.models import WebsitePage
from company_discovery.services.normalization import canonical_domain


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self._hidden = 0
        self._in_title = False
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._anchor_href = attributes.get("href")
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._anchor_href:
            self.links.append((self._anchor_href, " ".join(self._anchor_text)))
            self._anchor_href = None

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title = f"{self.title} {value}".strip()
        if self._anchor_href is not None:
            self._anchor_text.append(value)
        if not self._hidden:
            self.text.append(value)


class WebsiteClient:
    """Fetch a small official-site page pack anchored to a known root domain."""

    PAGE_TERMS = {
        "contact": ("contact", "locations", "location", "offices"),
        "about": ("about", "company", "who-we-are", "our-story", "ownership"),
    }

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_pages: int = 4,
        max_characters: int = 16000,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": "CompanyEnrichmentBot/1.0 (+business-information-research)"},
        )
        self._max_pages = max_pages
        self._max_characters = max_characters

    def fetch(self, domain: str) -> list[WebsitePage]:
        homepage = self._fetch_homepage(domain)
        if homepage is None:
            return []
        page, links = homepage
        pages = [page]
        for url, page_type in self._rank_links(page.url, domain, links):
            if len(pages) >= self._max_pages:
                break
            fetched = self._fetch_page(url, page_type)
            if fetched is not None and fetched.url not in {item.url for item in pages}:
                pages.append(fetched)
        return pages

    def _fetch_homepage(self, domain: str) -> tuple[WebsitePage, list[tuple[str, str]]] | None:
        for scheme in ("https", "http"):
            result = self._request(f"{scheme}://{domain}", "homepage")
            if result is not None:
                return result
        return None

    def _fetch_page(self, url: str, page_type: str) -> WebsitePage | None:
        result = self._request(url, page_type)
        return result[0] if result else None

    def _request(self, url: str, page_type: str) -> tuple[WebsitePage, list[tuple[str, str]]] | None:
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            return None
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return None
        parser = _PageParser()
        parser.feed(response.text)
        text = "\n".join(parser.text)[: self._max_characters]
        return (
            WebsitePage(url=str(response.url), title=parser.title, text=text, page_type=page_type),
            parser.links,
        )

    def _rank_links(
        self, base_url: str, domain: str, links: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        ranked: list[tuple[int, str, str]] = []
        seen: set[str] = set()
        for href, label in links:
            url = urljoin(base_url, href).split("#", 1)[0]
            if url in seen or canonical_domain(urlparse(url).hostname or "") != domain:
                continue
            haystack = f"{urlparse(url).path} {label}".lower()
            for priority, (page_type, terms) in enumerate(self.PAGE_TERMS.items()):
                if any(term in haystack for term in terms):
                    seen.add(url)
                    ranked.append((priority, url, page_type))
                    break
        return [(url, page_type) for _, url, page_type in sorted(ranked)]

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
