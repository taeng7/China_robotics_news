# -*- coding: utf-8 -*-
"""
지난 24시간 내 기사만 수집 + 리서치 요약 출력
"""

import os, re, json, hashlib, pathlib, yaml, requests, feedparser
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from lxml import html as lhtml
from jinja2 import Template
from requests.adapters import HTTPAdapter, Retry

try:
    import trafilatura
except Exception:
    trafilatura = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# ===== 설정 =====
LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Seoul"))
WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", "24"))
SKIP_HTML = os.environ.get("SKIP_HTML", "0") == "1"
EXTRACT_BODY = os.environ.get("EXTRACT_BODY", "1") == "1"

# ===== 템플릿 =====
TEMPLATE = """<!doctype html><meta charset="utf-8">
<title>China Robotics & AI — Last {{hours}}h</title>
<style>
body{font-family:system-ui,apple-system,sans-serif;margin:24px;max-width:900px}
.grid{display:grid;gap:12px}
.item{padding:12px;border:1px solid #eee;border-radius:12px}
.tags{opacity:.7;font-size:12px}
.meta{opacity:.8;font-size:13px;margin-bottom:12px}
.summary{padding:12px;margin:12px 0;border:2px solid #ddd;border-radius:12px;background:#fafafa}
h1{margin-bottom:4px}
</style>
<h1>China Robotics & AI — Last {{hours}}h</h1>
<div class=meta>Window: {{win_start}} → {{win_end}} ({{tz}})<br>Generated: {{generated}}</div>

<div class=summary>
<b>리서치 요약</b><br>
- 소스 수: {{n_sources}} 개<br>
- 기사 후보 수: {{n_candidates}} 개<br>
- 키워드 필터 후 최종 기사: {{n_final}} 개<br>
</div>

<input id=q placeholder="검색/筛选..." oninput="f(this.value)" style="padding:10px;border:1px solid #ddd;border-radius:10px;width:100%;max-width:520px">
<div class=grid id=list></div>
<script>
let data=__DATA__,el=document.getElementById('list');
function r(x){el.innerHTML=x.map(i=>`<div class=item>
<div class=tags>${i.source} · ${i.tags.join(', ')}</div>
<h3><a href="${i.link}" target=_blank rel=noopener>${i.title}</a></h3>
<div>${i.summary||''}</div>
<div class=tags>${new Date(i.date).toLocaleString()}</div>
</div>`).join('');}
function f(q){q=q.toLowerCase();r(data.filter(i=>(i.title+i.summary+i.source).toLowerCase().includes(q)))} r(data);
</script>"""

# ===== HTTP 세션 (재시도) =====
def build_session():
    s = requests.Session()
    retries = Retry(total=2, backoff_factor=0.6,
                    status_forcelist=[429,500,502,503,504],
                    allowed_methods=["GET","HEAD","OPTIONS"])
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; RLWRLD-NewsBot/1.0; +https://github.com/)",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ko;q=0.7",
    })
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

SESSION = build_session()
def http_get(url, timeout=15): return SESSION.get(url, timeout=timeout)

# ===== 유틸 =====
def load_yaml(path):
    """YAML 파일 로드"""
    return yaml.safe_load(open(path, 'r', encoding='utf-8'))

def sha(s): return hashlib.sha1(s.encode('utf-8')).hexdigest()
def now_utc(): return datetime.now(timezone.utc)
def now_utc_iso(): return now_utc().isoformat(timespec="seconds")

# ===== 시간 윈도우 =====
def window_bounds():
    end_local = datetime.now(LOCAL_TZ)
    start_local = end_local - timedelta(hours=WINDOW_HOURS)
    return start_local, end_local

WIN_START_LOCAL, WIN_END_LOCAL = window_bounds()

def in_window(dt_aware: datetime | None) -> bool:
    if not dt_aware: return False
    dt_local = dt_aware.astimezone(LOCAL_TZ)
    return WIN_START_LOCAL <= dt_local <= WIN_END_LOCAL

def parse_dt_any(s: str | None):
    if not s: return None
    try:
        from dateutil import parser as dtparser
        d = dtparser.parse(s)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except: return None

def extract_published_from_html(html_text: str):
    try:
        doc = lhtml.fromstring(html_text)
        meta_xpaths = [
            "//meta[@property='article:published_time']/@content",
            "//meta[@name='article:published_time']/@content",
            "//meta[@itemprop='datePublished']/@content",
            "//meta[@name='pubdate']/@content",
            "//meta[@property='og:updated_time']/@content",
            "//time[@datetime]/@datetime",
        ]
        for xp in meta_xpaths:
            vals = doc.xpath(xp)
            if vals:
                dt = parse_dt_any(vals[0])
                if dt: return dt
    except: return None
    return None

def clean_text(s: str) -> str:
    return (s or "").strip().replace("\u3000"," ").replace("\xa0"," ")

# ===== 수집기 =====
def fetch_rss(url: str):
    try:
        r = http_get(url, timeout=20); r.raise_for_status()
        d = feedparser.parse(r.content)
        out=[]
        for e in d.entries:
            pub=None
            for key in ["published_parsed","updated_parsed","created_parsed"]:
                st = getattr(e, key, None)
                if st: pub=datetime(*st[:6],tzinfo=timezone.utc); break
            if not in_window(pub): continue
            title=clean_text(e.get("title",""))
            link=e.get("link","")
            summ=clean_text((e.get("summary") or e.get("description") or "")[:400])
            out.append({"title":title,"link":link,"summary":summ,"date":pub.isoformat()})
        return out
    except Exception as ex:
        print(f"[WARN][RSS] {url} -> {ex}")
        return []

def fetch_html_window_items(list_url: str, link_pattern: str | None, limit=20):
    if SKIP_HTML:
        print(f"[INFO] SKIP_HTML=1 skip {list_url}"); return []
    try:
        r=http_get(list_url,timeout=20); r.raise_for_status()
        doc=lhtml.fromstring(r.text)
    except Exception as ex:
        print(f"[WARN][HTML:list] {list_url} -> {ex}"); return []
    rx=re.compile(link_pattern,re.I) if link_pattern else None
    seen,items=set(),[]
    for a in doc.xpath("//a[@href]"):
        href=a.get("href"); 
        if not href: continue
        href=requests.compat.urljoin(list_url,href)
        if rx and not rx.search(href): continue
        if href in seen: continue
        seen.add(href)
        try:
            art=http_get(href,timeout=20); art.raise_for_status()
            pub=extract_published_from_html(art.text)
            if not in_window(pub): continue
            title=clean_text(a.text_content()) or href
            summary=""
            if EXTRACT_BODY and trafilatura:
                try:
                    dl=trafilatura.extract(art.text) or ""
                    if dl: summary=clean_text(dl[:320])
                except: pass
            items.append({"title":title,"link":href,"summary":summary,
                          "date":(pub or datetime.now(timezone.utc)).isoformat()})
            if len(items)>=limit: break
        except Exception as ex:
            print(f"[WARN][HTML:detail] {href} -> {ex}")
            continue
    return items

# ===== 메인 =====
def main():
    feeds=load_yaml(ROOT/"feeds.yml")["feeds"]
    kw=load_yaml(ROOT/"keywords.yml")
    include=[re.compile(p,re.I) for p in kw.get("include",[])]
    exclude=[re.compile(p,re.I) for p in kw.get("exclude",[])]

    items,seen=[],set()
    total_candidates=0

    for f in feeds:
        name=f["name"]; url=f["url"]; typ=f.get("type","rss"); tags=f.get("tags",[])
        candidates=[]
        try:
            if typ=="rss": candidates=fetch_rss(url)
            else: candidates=fetch_html_window_items(url,f.get("link_pattern"),limit=20)
        except Exception as ex:
            print(f"[WARN][SOURCE] {name} -> {ex}")
        total_candidates+=len(candidates)

        for it in candidates:
            text=(it["title"]+" "+it.get("summary",""))
            if include and not any(p.search(text) for p in include): continue
            if exclude and any(p.search(text) for p in exclude): continue
            key=sha(it["link"] or it["title"])
            if key in seen: continue
            seen.add(key)
            it.update({"source":name,"tags":tags})
            items.append(it)

    items.sort(key=lambda x:x["date"],reverse=True)

    # 산출물 저장
    DOCS.mkdir(parents=True,exist_ok=True)
    (DOCS/"data.json").write_text(json.dumps(items,ensure_ascii=False,indent=2),"utf-8")

    html=Template(TEMPLATE).render(
        hours=WINDOW_HOURS,
        win_start=WIN_START_LOCAL.strftime("%Y-%m-%d %H:%M"),
        win_end=WIN_END_LOCAL.strftime("%Y-%m-%d %H:%M"),
        tz=str(LOCAL_TZ),
        generated=datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"),
        n_sources=len(feeds),
        n_candidates=total_candidates,
        n_final=len(items)
    )
    html=html.replace("__DATA__",json.dumps(items,ensure_ascii=False))
    (DOCS/"index.html").write_text(html,"utf-8")

    print(f"[INFO] Sources: {len(feeds)}, candidates={total_candidates}, final={len(items)}")

if __name__=="__main__":
    main()
