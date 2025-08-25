# -*- coding: utf-8 -*-
import re, json, time, hashlib, pathlib, yaml, traceback
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from jinja2 import Template

# Optional content extraction
try:
    import trafilatura
except Exception:
    trafilatura = None

from lxml import html as lhtml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

TEMPLATE = """<!doctype html><meta charset="utf-8">
<title>China Robotics & AI Clips</title>
<style>
body{font-family:system-ui,apple-system,sans-serif;margin:24px}
header{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:20px;margin:0}
.grid{display:grid;gap:12px}
.item{padding:12px;border:1px solid #eee;border-radius:12px}
.tag{opacity:.75;font-size:12px;margin-right:8px}
.tags{opacity:.65;font-size:12px}
.search{flex:1;min-width:240px;margin-left:auto;padding:10px;border-radius:10px;border:1px solid #e2e2e2}
h3{margin:.4rem 0}
</style>
<header>
  <h1>China Robotics & AI Clips</h1>
  <input class="search" placeholder="검색/筛选 (제목·요약·출처·태그)..." oninput="f(this.value)">
</header>
<div class="grid" id="list"></div>
<script>
let data = __DATA__;
const el = document.getElementById('list');
function render(items){
  el.innerHTML = items.map(i=>`<div class=item>
    <div class=tags><span class=tag>${i.source}</span> ${i.tags.map(t=>`<span class=tag>${t}</span>`).join('')}</div>
    <h3><a href="${i.link}" target=_blank rel=noopener>${i.title}</a></h3>
    <div>${i.summary||''}</div>
    <div class=tags>${new Date(i.date).toLocaleString()}</div>
  </div>`).join('');
}
function f(q){
  q=q.toLowerCase();
  render(data.filter(i=>(i.title+i.summary+i.source+i.tags.join(',')).toLowerCase().includes(q)));
}
render(data);
</script>"""

def load_yaml(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def sha(s: str) -> str:
    return hashlib.sha1(s.encode('utf-8')).hexdigest()

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def http_get(url, timeout=15):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; RLWRLD-NewsBot/1.0; +https://github.com/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ko;q=0.7",
    }
    return requests.get(url, headers=headers, timeout=timeout)

def extract_readable(url: str) -> str:
    if trafilatura is None:
        return ""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False) or ""
        return text
    except Exception:
        return ""

def is_recent(url_or_dt: str, days=14) -> bool:
    # crude heuristic: keep most items; actual recency will be based on feed timestamps where available.
    return True

def compile_patterns(patterns):
    return [re.compile(p, re.I) for p in patterns]

def match_any(text: str, pats) -> bool:
    return any(p.search(text) for p in pats) if pats else True

def clean_text(s: str) -> str:
    return (s or "").strip().replace("\u3000", " ").replace("\xa0", " ")

def discover_links_from_html(page_url: str, link_pattern: str | None, limit=40):
    try:
        r = http_get(page_url, timeout=20)
        r.raise_for_status()
        doc = lhtml.fromstring(r.text)
        links = []
        for a in doc.xpath("//a[@href]"):
            href = a.get("href")
            if not href:
                continue
            href = requests.compat.urljoin(page_url, href)
            text = a.text_content().strip()
            links.append((href, text))
        # regex filter
        if link_pattern:
            rp = re.compile(link_pattern, re.I)
            links = [(u,t) for (u,t) in links if rp.search(u)]
        # simple de-dup and cap
        seen, out = set(), []
        for u,t in links:
            if u in seen:
                continue
            seen.add(u)
            out.append((u,t))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []

def fetch_rss(url: str):
    d = feedparser.parse(url)
    out = []
    for e in d.entries:
        title = clean_text(e.get("title", ""))
        link = e.get("link", "")
        summ = clean_text((e.get("summary") or e.get("description") or "")[:600])
        date = None
        for k in ["published_parsed","updated_parsed","created_parsed"]:
            if getattr(e, k, None):
                date = datetime(*getattr(e, k)[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
                break
        out.append({"title": title, "link": link, "summary": summ, "date": date or now_iso()})
    return out

def main():
    cfg = load_yaml(ROOT / "feeds.yml")
    kw = load_yaml(ROOT / "keywords.yml")
    include = compile_patterns(kw.get("include", []))
    exclude = compile_patterns(kw.get("exclude", []))
    max_per_source = 40

    seen = set()
    items = []

    for feed in cfg["feeds"]:
        ftype = feed.get("type", "rss")
        name = feed.get("name", "source")
        tags = feed.get("tags", [])
        url = feed["url"]
        link_pat = feed.get("link_pattern")

        try:
            candidates = []
            if ftype == "rss":
                for it in fetch_rss(url)[:max_per_source]:
                    candidates.append(it)
            else:  # html
                for link, text in discover_links_from_html(url, link_pat, limit=max_per_source):
                    candidates.append({"title": clean_text(text) or link, "link": link, "summary": "", "date": now_iso()})
        except Exception as e:
            print("Fetch error:", name, url, e)
            continue

        for it in candidates:
            title = it["title"]
            link = it["link"]
            summary = it.get("summary","")
            text_for_filter = f"{title}\n{summary}"
            if include and not match_any(text_for_filter, include):
                # Fall back to fetching page title for HTML sources when empty
                if ftype == "html" and not match_any(title, include):
                    # try fetching and extracting a short text to check keywords
                    body = extract_readable(link)
                    if not match_any(body, include):
                        continue
                    if not summary and body:
                        summary = clean_text(body[:280]) + ("..." if len(body)>280 else "")
                else:
                    continue
            if exclude and match_any(text_for_filter, exclude):
                continue

            key = sha(link or title)
            if key in seen:
                continue
            seen.add(key)

            # auto-summary if empty and we can extract
            if not summary:
                body = extract_readable(link)
                if body:
                    summary = clean_text(body[:300]) + ("..." if len(body)>300 else "")

            items.append({
                "title": clean_text(title),
                "link": link,
                "summary": clean_text(summary),
                "source": name,
                "tags": tags,
                "date": it.get("date") or now_iso(),
            })

    # Sort newest first
    items.sort(key=lambda x: x["date"], reverse=True)

    # Write artifacts
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")

    html = Template(TEMPLATE.replace("__DATA__", json.dumps(items, ensure_ascii=False))).render()
    (DOCS / "index.html").write_text(html, "utf-8")

    print(f"Collected {len(items)} items from {len(cfg['feeds'])} sources.")

if __name__ == "__main__":
    main()
