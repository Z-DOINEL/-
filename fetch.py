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
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, quote
from urllib import robotparser

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_PATH = os.path.join(BASE_DIR, "data.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventTrackerBot/1.0)"}
TIMEOUT = 15


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
    url = "https://cn.bing.com/news/search?q=" + quote(query) + "&format=rss"
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "pub_date": pub_date,
                              "source": f"关键词：{name}"})
    except Exception as e:
        print(f"[警告] 抓取关键词「{name}」失败：{e}")
    return items


def fetch_official_page(name, url):
    items = []
    if not is_scraping_allowed(url):
        print(f"[跳过] 「{name}」禁止自动抓取：{url}")
        return items
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        seen = set()
        for a in soup.find_all("a"):
            text = (a.get_text() or "").strip()
            href = a.get("href") or ""
            if len(text) < 8 or len(text) > 100:
                continue
            if not href or href.startswith("javascript") or href.startswith("#"):
                continue
            full_link = href if href.startswith("http") else _join_url(url, href)
            if full_link in seen:
                continue
            seen.add(full_link)
            items.append({"title": text, "link": full_link, "pub_date": "",
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

    # 只保留最近800条，避免数据无限增长
    data["items"] = sorted(data["items"], key=lambda x: x.get("first_seen", ""), reverse=True)[:800]
    data["last_run"] = now

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"本次运行完成，新增 {new_count} 条内容，共 {len(data['items'])} 条。")


if __name__ == "__main__":
    main()
