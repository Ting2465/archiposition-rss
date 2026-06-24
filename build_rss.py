"""
archiposition.com (有方) RSS feed 生成器

策略:
  1. 抓 sitemap.xml 索引, 拿到 2026-06 等月度子 sitemap
  2. 按 lastmod 倒序合并, 抓前 ~110 个 URL
  3. 逐个抓详情页, 从 og:title / og:description / og:image 提取
  4. 拼成标准 RSS 2.0 XML

输出: ./archiposition.xml
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

OUTPUT = Path(__file__).parent / "archiposition.xml"
TARGET_COUNT = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.archiposition.com/",
}

SITE_URL = "https://www.archiposition.com/"
SITEMAP_INDEX = f"{SITE_URL}sitemap.xml"
FEED_URL = "https://{USER}.github.io/{REPO}/archiposition.xml"

# ---------------------------------------------------------------------------
# 1. 抓取工具
# ---------------------------------------------------------------------------

def fetch(url: str, *, timeout: int = 30, retries: int = 3) -> str:
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                charset = r.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            print(f"  [重试 {i+1}/{retries}] {url}  err={type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(2 + i * 2)
    raise RuntimeError(f"fetch failed: {url}  last_err={last_err}")


# ---------------------------------------------------------------------------
# 2. sitemap 处理 (两层: 索引 -> 月度)
# ---------------------------------------------------------------------------

def parse_sitemap_index(xml_text: str) -> list[str]:
    """解析 sitemap index, 返回所有子 sitemap 的 URL"""
    # sitemapindex 默认 namespace
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out = []
    for sm in root.findall("sm:sitemap", ns):
        loc = sm.findtext("sm:loc", "", ns)
        lastmod = sm.findtext("sm:lastmod", "", ns)
        if loc and "sitemap-pt-items" in loc:
            out.append({"loc": loc, "lastmod": lastmod})
    return out


def parse_sitemap(xml_text: str) -> list[dict]:
    """解析月度 sitemap, 返回所有文章 URL + lastmod"""
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out = []
    for url in root.findall("sm:url", ns):
        loc = url.findtext("sm:loc", "", ns)
        lastmod = url.findtext("sm:lastmod", "", ns)
        if loc and "/items/" in loc:
            out.append({"loc": loc, "lastmod": lastmod})
    return out


# ---------------------------------------------------------------------------
# 3. 详情页解析
# ---------------------------------------------------------------------------

def parse_detail(html_text: str) -> dict:
    """有方详情页没有 og:* / twitter:*, 改用 <title> + 正文里第一张大图 + 项目元信息"""

    # 标题: <title> 标签, 去掉 " – 有方" / "- 有方" / "| 有方" 后缀
    title = ""
    m = re.search(r"<title>([^<]+)</title>", html_text)
    if m:
        title = html.unescape(m.group(1)).strip()
        # 去掉尾部
        title = re.sub(r"\s*[\-–|]\s*有方\s*$", "", title)

    # 摘要: 抓取正文开头, 通常包含"项目地点 / 建成时间 / 建筑面积"
    desc = ""
    m = re.search(
        r'(设计单位[^<]{0,200}?)(?=</p>|</div>|<p[^>]*>)',
        html_text,
    )
    if m:
        desc = strip_html(m.group(1))
    if not desc:
        # fallback: 抓正文第一个 <p> 长段落
        for m in re.finditer(r"<p[^>]*>([^<]{30,300})</p>", html_text):
            t = strip_html(m.group(1))
            if t and "本文" not in t and len(t) > 20:
                desc = t[:200]
                break

    # 封面: 第一张 image.archiposition.com 的大图 (过滤 ?w= 这种 query string)
    image = ""
    seen = set()
    for m in re.finditer(
        r'(https?://image\.archiposition\.com/[^"\'\s)]+)',
        html_text,
    ):
        u = m.group(1)
        # 去掉 query string
        if "?" in u:
            u = u.split("?", 1)[0]
        if u in seen:
            continue
        seen.add(u)
        # 过滤头像/小图标: 路径里包含 /avatar/, /icon, /logo, /head-, /wechat
        low = u.lower()
        if any(k in low for k in ("/avatar", "/icon", "/logo", "head-", "wechat", "button")):
            continue
        # 排除缩略图尺寸: 看是否带 -150x150 / -300x 这种
        if re.search(r"-\d{2,3}x\d{2,3}\.", u):
            continue
        # 排除 logo svg
        if u.endswith(".svg") or u.endswith(".ico"):
            continue
        image = u
        break

    # 发布时间: 从正文里找 "2026.06.24 14:53" 格式
    pub = ""
    m = re.search(r"\b(20\d{2})[.\-/](\d{2})[.\-/](\d{2})\s+(\d{2}):(\d{2})\b", html_text)
    if m:
        y, mo, d, h, mi = m.groups()
        pub = f"{y}-{mo}-{d}T{h}:{mi}:00"

    return {
        "title": title,
        "description": desc,
        "image": image,
        "pub": pub,
    }


# ---------------------------------------------------------------------------
# 4. 工具
# ---------------------------------------------------------------------------

def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def iso_to_rfc822(iso: str) -> str:
    if not iso:
        return ""
    try:
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        elif re.match(r"\d{4}-\d{2}-\d{2}$", iso):
            dt = datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            return ""
        return format_datetime(dt, usegmt=True)
    except (ValueError, TypeError) as e:
        print(f"  [iso 解析失败] {iso!r}  {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------

def main():
    cache_dir = Path(__file__).parent / ".cache"
    cache_dir.mkdir(exist_ok=True)
    home_cache = cache_dir / "_sitemap_index.xml"

    # 1) 抓 sitemap index
    print("[1/4] 抓取 sitemap index...")
    if home_cache.exists() and (time.time() - home_cache.stat().st_mtime) < 3600:
        sitemap_index_xml = home_cache.read_text(encoding="utf-8", errors="replace")
        print(f"  使用缓存: {home_cache}")
    else:
        sitemap_index_xml = fetch(SITEMAP_INDEX, timeout=60)
        home_cache.write_text(sitemap_index_xml, encoding="utf-8")

    sub_sitemaps = parse_sitemap_index(sitemap_index_xml)
    # 只取文章(items)子 sitemap
    print(f"  找到 {len(sub_sitemaps)} 个 items 子 sitemap")
    # 按 lastmod 倒序
    sub_sitemaps.sort(key=lambda x: x["lastmod"], reverse=True)

    # 2) 取最近几个月的 sitemap, 抓文章 URL
    print("[2/4] 抓取月度 sitemap ...")
    all_entries = []
    seen_urls = set()
    for sm in sub_sitemaps[:4]:  # 4 个月足够凑 100+
        try:
            print(f"  {sm['loc']}")
            xml_text = fetch(sm["loc"], timeout=30)
            for e in parse_sitemap(xml_text):
                if e["loc"] not in seen_urls:
                    seen_urls.add(e["loc"])
                    all_entries.append(e)
        except Exception as ex:
            print(f"  [跳过] {ex}")

    # 按 lastmod 倒序
    all_entries.sort(key=lambda x: x["lastmod"], reverse=True)
    print(f"  共收集 {len(all_entries)} 个文章 URL")

    # 留余量: 抓前 120 个
    need = max(TARGET_COUNT, 0)
    to_fetch = all_entries[: need + 20]
    print(f"[3/4] 需补 {need} 条, 准备抓取 {len(to_fetch)} 个详情页 (含余量)")

    extra_posts = []
    fail_count = 0
    for i, e in enumerate(to_fetch):
        if len(extra_posts) >= need:
            break
        try:
            print(f"  [{i+1}/{len(to_fetch)}] {e['loc']}")
            detail_html = fetch(e["loc"], timeout=20)
            d = parse_detail(detail_html)
            if not d["title"]:
                print(f"    [空标题, 跳过]")
                fail_count += 1
                continue
            pub = d["pub"] or e["lastmod"]
            extra_posts.append({
                "url": e["loc"],
                "title": d["title"],
                "description": d["description"],
                "cover": d["image"],
                "date_gmt": pub,
                "id": None,
            })
            time.sleep(0.8)
        except Exception as ex:
            print(f"    [失败] {ex}")
            fail_count += 1

    print(f"  详情页成功: {len(extra_posts)}, 失败: {fail_count}")
    all_posts = extra_posts[:TARGET_COUNT]
    print(f"[4/4] 最终 {len(all_posts)} 条, 开始生成 RSS XML")

    build_rss(all_posts)
    print(f"\n✅ 已生成: {OUTPUT}  ({OUTPUT.stat().st_size} bytes, {len(all_posts)} items)")
    return len(all_posts), fail_count


def build_rss(all_posts: list[dict]):
    build_time = format_datetime(datetime.now(timezone.utc), usegmt=True)
    ATOM = "http://www.w3.org/2005/Atom"
    ET.register_namespace("atom", ATOM)
    ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "有方空间 archiposition.com 最新文章"
    ET.SubElement(channel, "link").text = SITE_URL
    ET.SubElement(channel, "description").text = (
        "有方 - 高品质建筑资讯门户。本 feed 自动抓取最近 100 篇文章的标题、摘要与封面。"
    )
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "lastBuildDate").text = build_time
    ET.SubElement(channel, "generator").text = "archiposition-rss GitHub Action"

    sl = ET.SubElement(channel, f"{{{ATOM}}}link")
    sl.set("href", os.environ.get("FEED_URL", "https://example.com/archiposition.xml"))
    sl.set("rel", "self")
    sl.set("type", "application/rss+xml")

    for p in all_posts:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = p["title"]
        ET.SubElement(item, "link").text = p["url"]
        guid = f"archiposition-{p.get('id') or p['url'].rsplit('/', 1)[-1]}"
        g = ET.SubElement(item, "guid", isPermaLink="false")
        g.text = guid

        rfc = iso_to_rfc822(p["date_gmt"])
        if rfc:
            ET.SubElement(item, "pubDate").text = rfc

        desc_parts = []
        if p["cover"]:
            desc_parts.append(
                f'<p><img src="{html.escape(p["cover"])}" alt="{html.escape(p["title"])}" /></p>')
        if p["description"]:
            desc_parts.append(f"<p>{html.escape(p['description'])}</p>")
        if desc_parts:
            ET.SubElement(item, "description").text = "\n".join(desc_parts)

        if p["cover"]:
            enc = ET.SubElement(item, "enclosure")
            enc.set("url", p["cover"])
            enc.set("type", "image/jpeg")

    ET.indent(rss, space="  ")
    tree = ET.ElementTree(rss)
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    try:
        n, f = main()
        sys.exit(0 if n >= 50 else 1)
    except Exception as e:
        print(f"\n❌ 失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
