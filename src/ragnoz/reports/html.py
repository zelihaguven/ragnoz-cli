from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any


def _safe(value: Any, redact: bool) -> str:
    text = str(value if value is not None else "")
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    if redact:
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
        text = re.sub(r"(?i)(api[_-]?key|token|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
        if len(text) > 180:
            text = text[:150] + "… [REDACTED_TEXT]"
    return html.escape(text)


def _scrub_data(value: Any, redact: bool) -> Any:
    secret_names = {"token", "secret", "password", "credential", "credentials", "api_key", "apikey",
                    "authorization", "private_key", "client_secret", "access_token", "auth_token"}
    if isinstance(value, dict):
        def hidden(key: Any) -> bool:
            name = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            return name in secret_names or name.endswith(("_api_key", "_token", "_secret", "_password", "_credential"))
        return {str(key): "[REDACTED]" if hidden(key)
                else _scrub_data(item, redact) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_data(item, redact) for item in value]
    if isinstance(value, str):
        cleaned = re.sub(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
        cleaned = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", cleaned)
        return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", cleaned) if redact else cleaned
    return value


def render_html(
    evaluation: dict[str, Any], diagnosis: dict[str, Any] | None = None, redact: bool = False,
    title: str = "RAGnoz run report",
) -> str:
    metrics = evaluation.get("metrics", {})
    rows = evaluation.get("items", [])
    findings = (diagnosis or {}).get("findings", [])
    recs = (diagnosis or {}).get("recommendations", [])
    profile = (diagnosis or {}).get("profile", {})
    metric_cards = []
    for key, value in metrics.items():
        if isinstance(value, (float, int)) or value is None:
            display = "—" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))
            metric_cards.append(f'<div class="metric"><small>{_safe(key, redact)}</small><strong>{display}</strong><span>n={metrics.get("n", 0)}</span></div>')
    row_html = "".join(
        f'<tr><td>{_safe(row.get("question_id"), False)}</td><td>{_safe(row.get("attribution"), False)}</td>'
        f'<td>{"✓" if row.get("correct") else "×" if row.get("correct") is False else "—"}</td>'
        f'<td>{_safe("[redacted]" if redact else row.get("answer", ""), redact)}</td>'
        f'<td>{_safe("[redacted]" if redact else row.get("reason", ""), redact)}</td></tr>' for row in rows
    )
    finding_html = "".join(f'<li><b>{_safe(f.get("id"),False)} · {_safe(f.get("title"),redact)}</b><br><span>{_safe(f.get("measured"),redact)}; eşik: {_safe(f.get("threshold"),redact)}; güven: {_safe(f.get("confidence"),False)}</span><br><span>{_safe(", ".join(f.get("item_ids",[])),False)}</span></li>' for f in findings)
    rec_html = "".join(f'<li><b>{_safe(r.get("id"),False)} [{_safe(r.get("confidence"),False)}] · {_safe(r.get("target_module"),False)}</b><p>{_safe(r.get("hypothesis"),redact)}</p><p><strong>Değişiklik:</strong> {_safe(r.get("change"),redact)}</p><p><strong>Deney:</strong> {_safe(json.dumps(r.get("experiment",{}),ensure_ascii=False),redact)}</p><p><strong>Etki tavanı:</strong> {_safe(json.dumps(r.get("expected_impact",{}),ensure_ascii=False),False)}</p></li>' for r in recs)
    unknowns = (diagnosis or {}).get("cannot_infer", [])
    safe_profile = _scrub_data(profile, redact)
    serialized = json.dumps({"metrics": metrics, "profile": safe_profile}, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{_safe(title,False)}</title>
<style>
:root{{--ink:#17283d;--paper:#f6f4ef;--line:#d5d8d9;--signal:#d97732;--teal:#197f77;--muted:#65717a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
header{{padding:2rem max(1.25rem,calc((100vw - 1100px)/2));background:var(--ink);color:#faf8f2}}header small{{color:#9dd4c9;letter-spacing:.12em;text-transform:uppercase}}h1{{margin:.25rem 0;font-size:2rem}}main{{max-width:1100px;margin:2rem auto;padding:0 1.25rem}}h2{{margin-top:2.5rem;border-bottom:1px solid var(--line);padding-bottom:.5rem}}.meta{{display:flex;gap:1rem;flex-wrap:wrap;color:#d5dce0}}.metrics{{display:flex;flex-wrap:wrap;gap:.75rem;margin:1rem 0}}.metric{{border:1px solid var(--line);background:white;padding:.8rem 1rem;min-width:140px;display:flex;flex-direction:column}}.metric small,.metric span{{color:var(--muted)}}.metric strong{{font-size:1.4rem;font-variant-numeric:tabular-nums}}.pill{{display:inline-block;background:#fbe3d0;color:#773c11;padding:.2rem .6rem;border-radius:99px}}table{{width:100%;border-collapse:collapse;background:white;font-size:.92rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid var(--line);vertical-align:top}}th{{background:#e8eceb}}td:first-child{{font-family:ui-monospace,monospace;white-space:nowrap}}li{{margin:1rem 0;padding-left:.3rem}}footer{{border-top:1px solid var(--line);margin-top:3rem;padding:1rem 0;color:var(--muted)}}.note{{border-left:4px solid var(--signal);padding:.75rem 1rem;background:#fff8f1}}@media(max-width:700px){{table{{font-size:.78rem}}th,td{{padding:.4rem}}}}
</style><header><small>RAGnoz · offline report</small><h1>{_safe(title,False)}</h1><div class="meta"><span class="pill">Paradigma: {_safe(profile.get("paradigm","not diagnosed"),False)}</span><span>Akış: {_safe(profile.get("flow","unknown"),False)}</span><span>Gözlem: {_safe(profile.get("observability","unknown"),False)}</span><span>{'Redacted' if redact else 'Local data'}</span></div></header>
<main><h2>Metrikler</h2><div class="metrics">{''.join(metric_cards)}</div><p class="note">Her oran n ile yorumlanmalıdır. n&lt;30 ise sonuç küçük örneklem uyarısı taşır. Paradigma bir kalite puanı değildir.</p>
<h2>Teşhis bulguları ({len(findings)})</h2><ul>{finding_html or '<li>İzlenebilir bulgu üretilmedi.</li>'}</ul>
<h2>Kanıta dayalı öneriler ({len(recs)})</h2><ul>{rec_html or '<li>Şu an öneri yok.</li>'}</ul>
<h2>Bu sonuçtan çıkarılamayanlar</h2><ul>{''.join(f'<li>{_safe(x,False)}</li>' for x in unknowns) or '<li>Belirtilmedi.</li>'}</ul>
<h2>Soru bazında önce/sonra inceleme</h2><div style="overflow:auto"><table><thead><tr><th>Soru</th><th>Atıf</th><th>Doğru</th><th>Cevap</th><th>Gerekçe</th></tr></thead><tbody>{row_html}</tbody></table></div>
<footer>Tek dosyalı, çevrimdışı RAGnoz raporu. Bu araç ölçülmüş kanıt dışında mimari veya nedensellik iddiası kurmaz.</footer></main><script type="application/json" id="summary">{serialized}</script></html>'''


def write_html(path: str | Path, evaluation: dict[str, Any], diagnosis: dict[str, Any] | None = None, redact: bool = False) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(evaluation, diagnosis, redact=redact), encoding="utf-8", newline="\n")
    return target
