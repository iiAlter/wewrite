#!/usr/bin/env python3
"""
Fetch trending topics from multiple Chinese platforms.

Sources (all attempted in parallel, results merged and deduplicated):
  1. Weibo hot search (weibo.com/ajax/side/hotSearch)
  2. Toutiao hot board (toutiao.com/hot-event/hot-board)
  3. Baidu hot search (top.baidu.com/api/board)

Key feature: cross-platform grouping — topics that appear on multiple platforms
get a `cross_platform_score` for sorting/filtering.

Usage:
    python3 fetch_hotspots.py --limit 20
"""

import argparse
import json
import sys
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import requests

TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


# ---- Fetchers ----

def fetch_weibo() -> list[dict]:
    try:
        resp = requests.get(
            "https://weibo.com/ajax/side/hotSearch",
            headers={**HEADERS, "Referer": "https://weibo.com/"},
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = []
        for entry in data.get("data", {}).get("realtime", []):
            note = entry.get("note", "")
            if not note:
                continue
            items.append({
                "title": note,
                "source": "微博",
                "hot": entry.get("num", 0) or 0,
                "url": f"https://s.weibo.com/weibo?q=%23{note}%23",
                "description": entry.get("label_name", ""),
            })
        return items
    except Exception as e:
        print(f"[warn] weibo failed: {e}", file=sys.stderr)
        return []


def fetch_toutiao() -> list[dict]:
    try:
        resp = requests.get(
            "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = []
        for entry in data.get("data", []):
            title = entry.get("Title", "")
            if not title:
                continue
            items.append({
                "title": title,
                "source": "今日头条",
                "hot": int(entry.get("HotValue", 0) or 0),
                "url": entry.get("Url", ""),
                "description": "",
            })
        return items
    except Exception as e:
        print(f"[warn] toutiao failed: {e}", file=sys.stderr)
        return []


def fetch_baidu() -> list[dict]:
    try:
        resp = requests.get(
            "https://top.baidu.com/api/board?platform=wise&tab=realtime",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = []
        for card in data.get("data", {}).get("cards", []):
            top_content = card.get("content", [])
            if not top_content:
                continue
            entries = top_content[0].get("content", []) if isinstance(top_content[0], dict) else top_content
            for entry in entries:
                word = entry.get("word", "")
                if not word:
                    continue
                items.append({
                    "title": word,
                    "source": "百度",
                    "hot": int(entry.get("hotScore", 0) or 0),
                    "url": entry.get("url", ""),
                    "description": "",
                })
        return items
    except Exception as e:
        print(f"[warn] baidu failed: {e}", file=sys.stderr)
        return []


# ---- Keyword extraction ----

STOPWORDS = {"的", "了", "是", "在", "和", "与", "对", "就", "都", "不", "也", "有", "被", "说", "又", "这", "那", "个", "们"}

def extract_keywords(title: str) -> set[str]:
    """Extract significant keywords from a title."""
    # Remove punctuation, split into words
    words = re.findall(r'[\w]+', title)
    # Filter stopwords and short words
    return {w.lower() for w in words if w not in STOPWORDS and len(w) >= 2}


# ---- Topic preference scoring ----

# Preferred topics (higher = more preferred)
TOPIC_SCORES = {
    "ai": 5, "人工智能": 5, "大模型": 5, "gpt": 5, "chatgpt": 5, "claude": 5,
    "科技": 4, "技术": 4, "产品": 4, "发布": 4, "互联网": 4,
    "app": 3, "手机": 3, "数码": 3, "游戏": 3, "影视": 3, "综艺": 3,
    "教育": 3, "职场": 3, "就业": 3, "考研": 3, "高考": 3, "留学": 3,
    "明星": 2, "娱乐": 2, "热搜": 1,
}

# Blocked topics (political/controversial)
BLOCK_KEYWORDS = {
    "外交部", "伊朗", "特朗普", "中美", "中俄", "台湾", "香港", "新疆", "西藏",
    "抗议", "封禁", "审查", "政权", "政府", "党", "国家领导人",
}

def score_by_platform(items: list[dict]) -> list[dict]:
    """
    Group items by keyword similarity, then score each group by:
      - cross_platform_score: number of unique platforms
      - total_hot: sum of hot values across platforms
    Returns deduplicated items with cross_platform metadata.
    """
    if not items:
        return []

    # Build keyword → list of items
    keyword_map = defaultdict(list)
    for item in items:
        for kw in extract_keywords(item["title"]):
            keyword_map[kw].append(item)

    # Group items by shared keywords
    groups = []
    used = set()
    for item in items:
        if id(item) in used:
            continue
        group = {id(item)}
        group_items = [item]
        for kw in extract_keywords(item["title"]):
            for other in keyword_map[kw]:
                oid = id(other)
                if oid not in group:
                    group.add(oid)
                    group_items.append(other)
        for i in group:
            used.add(i)
        groups.append(group_items)

    # Score each group
    scored = []
    for group_items in groups:
        platforms = list({it["source"] for it in group_items})
        total_hot = sum(int(it.get("hot", 0) or 0) for it in group_items)
        # Pick the item with highest hot as representative
        rep = max(group_items, key=lambda x: int(x.get("hot", 0) or 0))
        scored.append({
            **rep,
            "cross_platform_score": len(platforms),
            "platforms": platforms,
            "total_hot": total_hot,
        })

    return scored


def topic_score(title: str) -> int:
    """Compute topic-preference score for a title."""
    t = title.lower()
    score = 0
    for kw, pts in TOPIC_SCORES.items():
        if kw in t:
            score += pts
    for kw in BLOCK_KEYWORDS:
        if kw in title:
            score = -100  # hard block
            break
    return score


def sort_and_filter(items: list[dict], limit: int) -> list[dict]:
    """
    Sort by: topic_preference DESC, cross_platform_score DESC, total_hot DESC.
    Political/blocked topics are pushed to bottom.
    """
    def sort_key(x):
        return (topic_score(x["title"]), x["cross_platform_score"], x["total_hot"])
    items.sort(key=sort_key, reverse=True)

    # Deprioritize blocked topics but don't fully hide them
    blocked = [x for x in items if topic_score(x["title"]) < 0]
    non_blocked = [x for x in items if topic_score(x["title"]) >= 0]

    result = non_blocked[:limit]
    # If we have room, show some blocked items at the end (for reference)
    remaining = limit - len(result)
    if remaining > 0 and blocked:
        result.extend(blocked[:remaining])

    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch trending topics (cross-platform)")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    all_items = []
    sources_ok = []
    sources_fail = []

    for name, fetcher in [("weibo", fetch_weibo), ("toutiao", fetch_toutiao), ("baidu", fetch_baidu)]:
        items = fetcher()
        if items:
            sources_ok.append(name)
            all_items.extend(items)
        else:
            sources_fail.append(name)

    # Cross-platform scoring
    all_items = score_by_platform(all_items)
    all_items = sort_and_filter(all_items, args.limit)

    tz = timezone(timedelta(hours=8))
    output = {
        "timestamp": datetime.now(tz).isoformat(),
        "sources": sources_ok,
        "sources_failed": sources_fail,
        "count": len(all_items),
        "items": all_items,
    }

    if not all_items:
        output["error"] = "All sources failed. SKILL.md should fall back to WebSearch."

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
