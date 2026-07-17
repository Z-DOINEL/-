# -*- coding: utf-8 -*-
"""
由 GitHub Actions 在云端定时执行（每天固定两个时间点），负责：
1. 读取 config.json 里的"展会门户网站"列表
2. 用无头浏览器（真正打开网页、等它加载完）去这些网站里找展会信息
3. 跟已有的 data.json 合并（不覆盖旧数据，只增量添加新条目，并清理已经办完的旧展会）
4. 把结果写回 data.json，交给 index.html 网页展示

之前"关键词搜索"和"通用官网监测"这两条路已经放弃不用了，
现在只保留"展会门户网站"这一种信息来源，因为它的信息格式更规整、更准确。
"""
import json
import os
import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from urllib import robotparser

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_PATH = os.path.join(BASE_DIR, "data.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventTrackerBot/1.0)"}
EVENT_DATE_PATTERN = re.compile(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?')


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


def _join_url(base, href):
    parsed = urlparse(base)
    if href.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return base.rstrip("/") + "/" + href


def fetch_exhibition_portal(name, url):
    """
    专门针对"展会门户网站"（比如eshow365.com这类）写的抓取规则：
    这类网站每条展会信息格式比较规整（分类标签+展会名称链接+场馆+日期），
    抓取思路是找到"指向展会详情页"的链接（网址里带 /zhanhui/html/数字_0.html 这种规律），
    再往它附近找日期。

    注意：这段代码没有在真实网络环境里跑通过（沙盒里无法访问这个网站），
    第一次实际部署后如果发现抓不到东西或者抓的位置不对，
    把运行日志发回去，需要照实际情况再调整。
    """
    items = []
    if not is_scraping_allowed(url):
        print(f"[跳过] 「{name}」禁止自动抓取：{url}")
        return items

    # 先用最简单直接的普通请求测试一下这个网站到底能不能连上（不用无头浏览器），
    # 用来区分"网站完全连不上/屏蔽了云服务器IP" 还是 "只是无头浏览器这种方式被特别拦截"
    try:
        diag_resp = requests.get(url, headers=HEADERS, timeout=15)
        print(f"[诊断] 普通请求「{name}」：状态码 {diag_resp.status_code}，返回内容长度 {len(diag_resp.text)} 字符")
    except Exception as diag_e:
        print(f"[诊断] 普通请求「{name}」也失败了：{diag_e}（说明大概率是网络层面连不上，不是无头浏览器的问题）")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        today = datetime.now(timezone.utc).date()

        detail_link_pattern = re.compile(r'/zhanhui/html/\d+_0\.html')

        for a in soup.find_all("a", href=detail_link_pattern):
            title = (a.get_text() or "").strip() or (a.get("title") or "").strip()
            href = a.get("href") or ""
            if not title or not href:
                continue
            full_link = href if href.startswith("http") else _join_url(url, href)
            if full_link in seen:
                continue
            seen.add(full_link)

            # 在这条链接所在的父容器文字里找日期（展会举办日期，不是发布日期）
            event_date = ""
            node = a.parent
            for _ in range(3):
                if node is None:
                    break
                text = node.get_text(" ", strip=True)
                m = EVENT_DATE_PATTERN.search(text)
                if m:
                    y, mo, d = (int(x) for x in m.groups())
                    try:
                        event_date = f"{y:04d}-{mo:02d}-{d:02d}"
                    except Exception:
                        pass
                    break
                node = node.parent

            # 只保留"还没举办/即将举办"的展会，已经开完超过2天的不要
            if event_date:
                try:
                    y, mo, d = (int(x) for x in event_date.split("-"))
                    if datetime(y, mo, d).date() < today - timedelta(days=2):
                        continue
                except Exception:
                    pass

            items.append({"title": title, "link": full_link, "pub_date": event_date,
                          "summary": "", "source": f"展会门户：{name}"})
    except Exception as e:
        print(f"[警告] 抓取展会门户「{name}」失败：{e}")
    return items


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
    for ex in config.get("exhibition_portals", []):
        if ex.get("enabled") is False:
            continue
        all_fetched.extend(fetch_exhibition_portal(ex["name"], ex["url"]))

    for it in all_fetched:
        item_id = make_id(it["link"], it["title"])
        if item_id not in existing_ids:
            data["items"].append({
                "id": item_id,
                "title": it["title"],
                "link": it["link"],
                "source": it["source"],
                "pub_date": it.get("pub_date", ""),
                "summary": it.get("summary", ""),
                "first_seen": now,
            })
            existing_ids.add(item_id)
            new_count += 1

    # 已经办完的旧展会（超过2天）从data.json里也清理掉，不只是新抓的才过滤
    today = datetime.now(timezone.utc).date()
    before_prune = len(data["items"])
    kept = []
    for it in data["items"]:
        pd = it.get("pub_date") or ""
        if pd:
            try:
                y, mo, d = (int(x) for x in pd.split("-"))
                if datetime(y, mo, d).date() < today - timedelta(days=2):
                    continue
            except Exception:
                pass
        kept.append(it)
    data["items"] = kept
    pruned_count = before_prune - len(data["items"])

    data["items"] = sorted(data["items"], key=lambda x: x.get("pub_date") or x.get("first_seen", ""))[:800]
    data["last_run"] = now

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"本次运行完成，新增 {new_count} 条内容，清理 {pruned_count} 条已过期展会，共 {len(data['items'])} 条。")


if __name__ == "__main__":
    main()
