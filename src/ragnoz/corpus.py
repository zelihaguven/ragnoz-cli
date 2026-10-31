from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote

import httpx


class _TextExtractor(HTMLParser):
    BLOCKS: ClassVar[set[str]] = {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "td", "th", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "math", "figure", "table"}:
            self.skip += 1
        if not self.skip and tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "math", "figure", "table"} and self.skip:
            self.skip -= 1
        if not self.skip and tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def load_revision_manifest(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError("Revision manifest bir liste olmalı")
    return data


def download_revision_corpus(manifest: list[dict[str, Any]], destination: str | Path) -> Path:
    """Download exact revision HTML; only writes under the user-selected destination."""
    target = Path(destination).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    with httpx.Client(timeout=35.0, headers={"User-Agent": "RAGnoz/0.1 (local open-corpus demo)"}) as client:
        for row in manifest:
            lang = str(row["lang"])
            revid = str(row["revid"])
            url = f"https://{lang}.wikipedia.org/w/rest.php/v1/revision/{quote(revid)}/html"
            for attempt in range(5):
                response = client.get(url)
                if response.status_code != 429:
                    response.raise_for_status()
                    break
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(5 * (2**attempt), 60)
                except ValueError:
                    delay = min(5 * (2**attempt), 60)
                if attempt == 4:
                    response.raise_for_status()
                time.sleep(max(1.0, delay))
            text = html_to_text(response.text)
            if len(text) < 100:
                raise ValueError(f"Revision {revid} içerik olarak boş görünüyor")
            pages.append({**row, "doc_id": f"{lang}_{row['pageid']}", "text": text,
                          "source_url": f"https://{lang}.wikipedia.org/w/index.php?oldid={revid}"})
            time.sleep(1.0)
    output = target / "pages.json"
    output.write_text(json.dumps(pages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    attribution = target / "ATTRIBUTION.md"
    lines = ["# Wiki-mini attribution", "", "Wikipedia text is licensed CC BY-SA 4.0. This local corpus was downloaded by explicit user command from pinned page revisions.", ""]
    for row in pages:
        lines.append(f"- [{row['title']} ({row['lang']})]({row['source_url']}) — revision {row['revid']}; CC BY-SA 4.0.")
    lines += ["", "License: https://creativecommons.org/licenses/by-sa/4.0/"]
    attribution.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
