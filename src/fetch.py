# -*- coding: utf-8 -*-
import re, json, hashlib, pathlib, yaml, requests, feedparser
from datetime import datetime, timezone, timedelta
from lxml import html as lhtml
from jinja2 import Template

try:
    import trafilatura
except:
    trafilatura = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# HTML 템플릿
TEMPLATE = """<!doctype html><meta charset="utf-8">
<title>China Robotics & AI Daily Clips</title>
<style>
body{font-family:system-ui,apple-system,sans-serif;margin:24px}
.grid{display:grid;gap:12px}
.item{padding:12px;border:1px solid #eee;border-radius:12px}
.tags{opacity:.7;font-size:12px}
</style>
<h1>China Robotics & AI Daily Clips (오늘 기사만)</h1>
<input id=q placeholder="검색/筛选..." oninput="f(this.value)" style="padding:10px;border:1px solid #ddd;border-radius:10px;width:100%;max-width:520px">
<div class=grid id=list></div>
<script>
let data=__DATA__,el=document.getElementById('list');
function r(x){el.innerHTML=x.map(i=>`<div class=item>
<div class=tags>${i.source} · ${i.tags.join(', ')}</div>
<h3><a href="${i.link}" target=_blank rel=noopener>${i.title}</a></h3>
<div>${i.summary||''}</div>
<div class=tags>${i.date}</div>
</div>`).join('');}
function f(q){q=q.toLowerCase();r(data.filter(i=>(i.title+i.summary+i.source).toLowerCase().includes(q)))} r(data);
</script>"""

def load_yaml(path):
    return yaml.safe_load(open(path, 'r', encoding='utf-8'))

def sha(s): return hashlib.sha1(s.encode('utf-8')).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def http_get(url):
    return requests.get(url, headers={"User-Agent":"Mozilla/5.0 RLWRLD/1.0"}, timeout=15)

def extract_readable(url: str) -> str:
    if not trafilatura: return ""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded: return ""
        return trafilatura.extract(downloaded) or ""
    except: return ""

def fetch_rss(url):
    d = feedparser.parse(http_get(url).content)
    out=[]
    for e in d.entries:
        title=(e.get("title") or "").strip()
        link=e.get("link","")
        summ=(e.get("summary") or e.get("description") or "")[:300]
        # 날짜 파싱
        pub=None
        for k in ["published_parsed","updated_parsed","created_parsed"]:
            if getattr(e,k,None):
                pub=datetime(*getattr(e,k)[:6],tzinfo=timezone.utc)
                break
        if not pub: pub=datetime.now(timezone.utc)
        out.append({"title":title,"link":link,"summary":summ,"date":pub.isoformat()})
    return out

def discover_links(page_url, pattern, limit=30):
    doc=lhtml.fromstring(http_get(page_url).text)
    rx=re.compile(pattern,re.I) if pattern else None
    links=[]
    for a in doc.xpath("//a[@href]"):
        href=a.get("href"); 
        if not href: continue
        href=requests.compat.urljoin(page_url,href)
        if rx and not rx.search(href): continue
        txt=a.text_content().strip()
        links.append({"title":txt or href,"link":href,"summary":"","date":now()})
        if len(links)>=limit: break
    return links

def main():
    feeds=load_yaml(ROOT/"feeds.yml")["feeds"]
    kw=load_yaml(ROOT/"keywords.yml")
    include=[re.compile(p,re.I) for p in kw.get("include",[])]
    exclude=[re.compile(p,re.I) for p in kw.get("exclude",[])]

    # 오늘 날짜(중국 표준시 기준)
    today=datetime.now(timezone(timedelta(hours=8))).date()

    items,seen=[],set()
    for f in feeds:
        name=f["name"]; url=f["url"]; typ=f.get("type","rss"); tags=f.get("tags",[])
        cand=fetch_rss(url) if typ=="rss" else discover_links(url,f.get("link_pattern"))
        for it in cand:
            text=it["title"]+" "+it.get("summary","")
            if include and not any(p.search(text) for p in include): continue
            if exclude and any(p.search(text) for p in exclude): continue
            # 날짜 필터: 오늘 것만
            try:
                pub=datetime.fromisoformat(it["date"].replace("Z","+00:00")).astimezone(timezone(timedelta(hours=8))).date()
            except: pub=today
            if pub!=today: continue

            key=sha(it["link"] or it["title"])
            if key in seen: continue
            seen.add(key)

            if not it["summary"]:
                body=extract_readable(it["link"])
                if body: it["summary"]=body[:300]
            it.update({"source":name,"tags":tags})
            items.append(it)

    items.sort(key=lambda x:x["date"],reverse=True)

    DOCS.mkdir(exist_ok=True,parents=True)
    (DOCS/"data.json").write_text(json.dumps(items,ensure_ascii=False,indent=2),"utf-8")
    html=Template(TEMPLATE.replace("__DATA__",json.dumps(items,ensure_ascii=False))).render()
    (DOCS/"index.html").write_text(html,"utf-8")

if __name__=="__main__":
    main()
