# -*- coding: utf-8 -*-
"""
由 GitHub Actions 在云端定时执行（每天固定两个时间点），负责：
1. 读取 config.json 里的关键词和官网列表
2. 抓取必应关键词新闻RSS + 官网页面链接
3. 和已有的 data.json 合并（不覆盖旧数据，只增量添加新条目）
4. 把结果写回 data.json，交给 index.html 网页展示

这个脚本本身不生成网页界面，只负责"抓数据、存数据"。
"""
import json
import os
import re
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, quote
from urllib import robotparser

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_PATH = os.path.join(BASE_DIR, "data.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventTrackerBot/1.0)"}
TIMEOUT = 15
RECENT_DAYS = 7  # 只保留最近7天内发布的内容，超过7天的不要

DATE_PATTERNS = [
    re.compile(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?'),
]


def is_recent_enough(pub_date_str):
    """没有日期信息时不过滤（交给前端标注"日期未知"），能解析出日期的才判断是否太老。"""
    if not pub_date_str:
        return True
    try:
        dt = parsedate_to_datetime(pub_date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) <= timedelta(days=RECENT_DAYS)
    except Exception:
        try:
            for pat in DATE_PATTERNS:
                m = pat.search(pub_date_str)
                if m:
                    y, mo, d = (int(x) for x in m.groups())
                    dt = datetime(y, mo, d, tzinfo=timezone.utc)
                    return (datetime.now(timezone.utc) - dt) <= timedelta(days=RECENT_DAYS)
        except Exception:
            pass
        return True


def extract_nearby_date(a_tag):
    """尝试从链接自身、父节点、祖父节点的文字里找发布日期，找不到就返回空字符串（不瞎猜）。"""
    node = a_tag
    for _ in range(3):
        if node is None:
            break
        try:
            text = node.get_text(" ", strip=True)
        except Exception:
            text = ""
        for pat in DATE_PATTERNS:
            m = pat.search(text)
            if m:
                y, mo, d = (int(x) for x in m.groups())
                try:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
                except Exception:
                    pass
        node = node.parent
    return ""


def make_id(link, title):
    raw = (link or "") + "||" + (title or "")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def is_scraping_allowed(url):
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(HEADERS["User-Agent"], url)
    except Exception:
        return True


def fetch_bing_rss(name, query):
    url = "https://www.bing.com/news/search?q=" + quote(query) + "&format=rss"
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        skipped_old = 0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if not (title and link):
                continue
            if not is_recent_enough(pub_date):
                skipped_old += 1
                continue
            items.append({"title": title, "link": link, "pub_date": pub_date,
                          "source": f"关键词：{name}"})
        if skipped_old:
            print(f"「{name}」过滤掉 {skipped_old} 条超过{RECENT_DAYS}天的旧内容")
    except Exception as e:
        print(f"[警告] 抓取关键词「{name}」失败：{e}")
    return items


def fetch_official_page(name, url):
    """
    用无头浏览器（真的打开网页、等JS跑完）去抓取，而不是只读最原始的HTML代码，
    这样能抓到那些"页面加载完之后才由JavaScript生成"的公告/活动链接，
    而不是只抓到写死在原始代码里的导航栏链接（常见的表现就是抓到的全是首页链接）。
    """
    items = []
    if not is_scraping_allowed(url):
        print(f"[跳过] 「{name}」禁止自动抓取：{url}")
        return items
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            # 不用"networkidle"这个太严格的等待条件——有些网站有持续的后台请求
            # （比如统计代码、广告脚本），永远达不到"完全没有网络活动"这个状态，
            # 导致白白等到超时。改成"页面基本内容加载完"就往下走，
            # 再额外多等几秒，给JS一点时间把动态内容渲染出来
            page.wait_for_timeout(4000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        base_netloc = urlparse(url).netloc
        for a in soup.find_all("a"):
            text = (a.get_text() or "").strip()
            href = a.get("href") or ""
            if len(text) < 8 or len(text) > 100:
                continue
            if not href or href.startswith("javascript") or href.startswith("#"):
                continue
            full_link = href if href.startswith("http") else _join_url(url, href)
            # 过滤掉指向首页/栏目页本身的链接（比如链接就是官网根地址），
            # 这类链接价值不大，容易造成"点开全是首页"的情况
            link_path = urlparse(full_link).path.strip("/")
            if urlparse(full_link).netloc == base_netloc and link_path == "":
                continue
            if full_link in seen:
                continue
            seen.add(full_link)
            found_date = extract_nearby_date(a)
            if found_date and not is_recent_enough(found_date):
                continue  # 找到日期但太老了，跳过
            items.append({"title": text, "link": full_link, "pub_date": found_date,
                          "source": f"官网：{name}"})
    except Exception as e:
        print(f"[警告] 抓取官网「{name}」失败：{e}")
    return items


def _join_url(base, href):
    parsed = urlparse(base)
    if href.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return base.rstrip("/") + "/" + href


def main():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"items": [], "last_run": None}

    existing_ids = {it["id"] for it in data["items"]}
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")
    new_count = 0

    all_fetched = []
    for kw in config.get("keywords", []):
        if kw.get("enabled") is False:
            continue
        all_fetched.extend(fetch_bing_rss(kw["name"], kw["q"]))
    for pg in config.get("official_pages", []):
        if pg.get("enabled") is False:
            continue
        all_fetched.extend(fetch_official_page(pg["name"], pg["url"]))

    for it in all_fetched:
        item_id = make_id(it["link"], it["title"])
        if item_id not in existing_ids:
            data["items"].append({
                "id": item_id,
                "title": it["title"],
                "link": it["link"],
                "source": it["source"],
                "pub_date": it.get("pub_date", ""),
                "first_seen": now,
            })
            existing_ids.add(item_id)
            new_count += 1

    # 已经存进data.json的老数据，如果知道真实发布日期且已经超过时效窗口，也清理掉
    # （不知道发布日期的保留，毕竟没法判断它到底是不是真的过时了）
    before_prune = len(data["items"])
    data["items"] = [
        it for it in data["items"]
        if not it.get("pub_date") or is_recent_enough(it["pub_date"])
    ]
    pruned_count = before_prune - len(data["items"])

    # 只保留最近800条，避免数据无限增长
    data["items"] = sorted(data["items"], key=lambda x: x.get("first_seen", ""), reverse=True)[:800]
    data["last_run"] = now

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"本次运行完成，新增 {new_count} 条内容，清理 {pruned_count} 条过期旧内容，共 {len(data['items'])} 条。")


if __name__ == "__main__":
    main()
