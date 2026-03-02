from __future__ import annotations

from typing import Any, List

from bs4 import BeautifulSoup


def _to_html_text(value: Any) -> str:
    if isinstance(value, dict) and "bd" in value:
        return str(value.get("bd") or "")
    if value is None:
        return ""
    return str(value)


def html_tte(value: Any) -> str:
    html = _to_html_text(value)
    soup = BeautifulSoup(html, "html.parser")
    if soup.title is None:
        return ""
    return soup.title.get_text(strip=True)


def html_sct(value: Any, css: Any) -> List[str]:
    selector = str(css).strip()
    if selector == "":
        return []
    html = _to_html_text(value)
    soup = BeautifulSoup(html, "html.parser")
    out: List[str] = []
    for node in soup.select(selector):
        out.append(node.get_text(" ", strip=True))
    return out

