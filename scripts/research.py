#!/usr/bin/env python3
"""
Step 3.2 — Research Search (v2)
搜索选题相关官方权威来源，生成结构化写作素材包。

优先级：
  A级（首选）：政府网站、上市公司公告、官方机构
  B级（辅助）：央视、财新、36kr、澎湃
  C级（舆情参考）：知乎、微博

升级点 v2：
  - raw_content=True 获取更干净的原文
  - BeautifulSoup 清洗 HTML 噪音（导航/广告/声明）
  - 多字段事实抽取：数字、人名、公司名、百分比
  - Tavily answer 优先作为核心引用

输出：写作素材包 Markdown
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────

CONFIG_PATHS = [
    Path.cwd() / "config.yaml",
    Path(__file__).parent.parent / "config.yaml",
]

def load_config():
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}

cfg = load_config()
# Env var overrides
for sec, keys in [("llm", ["api_key"]), ("image", ["api_key"])]:
    for k in keys:
        env_val = os.environ.get(f"WEWRITE_{sec.upper()}_{k.upper()}")
        if env_val:
            cfg.setdefault(sec, {})[k] = env_val

TAVILY_KEY = os.environ.get("TAVILY_API_KEY") or cfg.get("llm", {}).get("api_key", "") or cfg.get("image", {}).get("api_key", "")
if not TAVILY_KEY:
    print("Error: TAVILY_API_KEY not set", file=sys.stderr)
    sys.exit(1)

TAVILY_URL = "https://api.tavily.com/search"

# ── Source Tiers ───────────────────────────────────────────────────────────────

SOURCE_TIERS = {
    "A": [
        "gov.cn", "gov.uk", "gov.au",
        "who.int", "imf.org", "worldbank.org",
        "sec.gov", "csrc.gov.cn", "sse.com.cn", "szse.cn",
        "berkshirehathaway.com",
        "xinhuanet.com", "people.com.cn",
    ],
    "B": [
        # 国际权威
        "36kr.com", "caixin.com", "cls.cn", "yicai.com",
        "cctv.com", "thepaper.cn", "bjnews.com.cn",
        "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
        "scmp.com", "nikkei.com",
        # 中国头部财经（升级为B）
        "sina.com.cn", "sohu.com", "ifeng.com", "tencent.com",
        "eastmoney.com", "stock.stcn.com", "qq.com",
        "baidu.com", "zhihu.com",
    ],
}

def rate_source(url: str) -> str:
    u = url.lower()
    for tier in ["A", "B"]:
        for d in SOURCE_TIERS[tier]:
            if d in u:
                return tier
    return "C"

# ── Content Cleaning ─────────────────────────────────────────────────────────

def extract_main_content(html: str) -> str:
    """用 BeautifulSoup 提取正文，剔除噪音。"""
    soup = BeautifulSoup(html, "html.parser")
    # 移除噪音标签
    for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                               "aside", "form", "iframe", "svg"]):
        tag.decompose()
    # 移除含噪音词的标签
    noise_classes = ["comment", "footer", "sidebar", "ad", "banner", "popup",
                      "declare", "statement", "copyright", "nav", "menu"]
    for cls in noise_classes:
        for tag in soup.find_all(class_=re.compile(cls, re.I)):
            tag.decompose()
    # 尝试找 main / article
    main = soup.find("article") or soup.find("main") or soup.find("div", id="content") or soup.find("div", class_=re.compile("content|article|post", re.I))
    if main:
        text = main.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)
    # 去除重复空行
    lines = [l for l in text.split("\n") if l.strip() and len(l.strip()) > 10]
    return "\n".join(lines[:200])  # 保留前200行足够的事实提取

def fetch_and_clean(url: str) -> str:
    """用 Jina Reader 提取干净正文，比直接抓取更稳定。"""
    try:
        r = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain"},
            timeout=15
        )
        text = r.text
        # Jina 返回格式：Title: ...\nPublished Time: ...\nMarkdown Content:\n...
        # 去掉 Jina 的元数据头，保留正文
        if "Markdown Content:" in text:
            text = text.split("Markdown Content:", 1)[1]
        elif "Raw Content:" in text:
            text = text.split("Raw Content:", 1)[1]
        return text.strip()
    except Exception:
        return ""

# ── Search ─────────────────────────────────────────────────────────────────

def search_tavily(query: str, max_results: int = 10) -> list[dict]:
    payload = {
        "api_key": TAVILY_KEY,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": True,
        "include_raw_content": True,
        "include_images": False,
    }
    resp = requests.post(TAVILY_URL, json=payload, timeout=30)
    data = resp.json()
    if resp.status_code != 200:
        print(f"Tavily error: {data}", file=sys.stderr)
        return []
    return data.get("results", [])

# ── Fact Extraction ──────────────────────────────────────────────────────────

NUM_PATTERN = re.compile(
    r"[\d]{1,3}(?:,\d{3})+(?:\.\d+)?%?(?:亿|万|美元|人|次|年|月|日|点|%%|%)?|"
    r"\d+(?:\.\d+)?%?(?:亿|万|美元|人|次|年|月|日|点|%)?"
)

COMPANY_PATTERN = re.compile(
    r"(?:苹果|微软|谷歌|亚马逊|Meta|特斯拉|英伟达|谷歌|伯克希尔|可口可乐|美国运通|雪佛龙|埃克森美孚|宝洁|强生|富国银行|美国银行|摩根|腾讯|阿里|茅台|比亚迪|京东|百度)"
)

def extract_facts(text: str) -> tuple[list, list, list]:
    """从文本中抽取数字数据、金句、关键实体。"""
    numbers = []
    for m in NUM_PATTERN.finditer(text):
        val = m.group()
        if len(val) > 2:
            numbers.append(val.strip())

    # 金句：连续引号内的内容
    quotes = re.findall(r'"([^"]{10,200})"', text)
    quotes += re.findall(r'「([^」]{10,200})」', text)

    # 公司/人名
    companies = list(set(COMPANY_PATTERN.findall(text)))

    deduped_numbers = list(dict.fromkeys(numbers))[:15]
    deduped_quotes = list(dict.fromkeys(quotes))[:5]
    return deduped_numbers, deduped_quotes, companies

# ── Deduplicate & Rank ───────────────────────────────────────────────────────

def rank_and_dedup(results: list[dict]) -> list[dict]:
    seen = {}
    for r in results:
        tier = rate_source(r.get("url", ""))
        key = r.get("title", "")[:20]
        score = r.get("score", 0) * (3 if tier == "A" else 2 if tier == "B" else 1)
        if key not in seen or score > seen[key]["score"]:
            seen[key] = {"r": r, "score": score, "tier": tier}
    ranked = sorted(seen.values(), key=lambda x: -x["score"])
    return [x["r"] for x in ranked]

# ── Materials Package Generator ─────────────────────────────────────────────

def build_materials_package(topic: str, results: list[dict], tavily_answer: str = "") -> str:
    # 对所有来源用 Jina 拉干净正文（A/B/C 均可）
    clean_contents = {}
    for r in results[:6]:
            url = r.get("url", "")
            clean = fetch_and_clean(url)
            if clean:
                clean_contents[url] = clean
                print(f"  ✅ Jina fetched: {r.get('title','')[:40]}... ({len(clean)} chars)")
            else:
                print(f"  ⚠️  Jina failed: {url}")

    # 用干净正文替换 Tavily content
    for r in results:
        url = r.get("url", "")
        if url in clean_contents:
            r["_clean_content"] = clean_contents[url][:3000]  # 保留前3000字
        else:
            r["_clean_content"] = r.get("content", "")[:1000]
    tier_groups = defaultdict(list)
    for r in results:
        tier_groups[rate_source(r.get("url", ""))].append(r)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    md = f"""# 写作素材包

> 生成时间：{now} | 选题：{topic} | 可用来源：{len(results)} 条

## 核心结论（Tavily AI 综合）

> {tavily_answer or "(Tavily 未返回综合结论，请阅读下方来源提炼)"}  

来源：Tavily AI 搜索 | 可信度：综合评级

---

## 一、核心事实

"""
    # 按 A→B→C 顺序写
    for tier in ["A", "B", "C"]:
        items = tier_groups.get(tier, [])
        if not items:
            continue
        tier_label = "⭐ A级官方" if tier == "A" else "⭐ B级权威媒体" if tier == "B" else "  C级参考资料"
        md += f"### {tier_label}\n\n"
        for r in items[:4]:
            title = r.get("title", "").strip()
            content = (r.get("_clean_content") or r.get("content", "")).strip()[:400]
            url = r.get("url", "")
            md += f"**{title}**\n>{content[:300]}...\n>— [{title[:30]}]({url}) | 可信度：{tier}\n\n"
            # 抽事实
            numbers, quotes, _ = extract_facts(content)
            for n in numbers[:3]:
                md += f"- 数字：**{n}**\n"
            for q in quotes[:2]:
                md += f"- 引言：\"{q[:80]}\"\n"
        md += "\n"

    md += "## 二、关键数据\n\n"
    for r in (tier_groups.get("A", []) + tier_groups.get("B", []))[:6]:
        content = r.get("_clean_content") or r.get("content", "")
        numbers, _, _ = extract_facts(content)
        for n in numbers[:2]:
            md += f"- **{n}** — {r.get('title','')[:40]} | [来源]({r.get('url','')})\n"
    md += "\n## 三、各方立场\n\n"
    md += "_（根据信源立场整理，如有分歧会分别标注）_\n\n"
    # 从 Tavily answer 提取立场
    if tavily_answer:
        md += f"**巴菲特核心观点：**\n> {tavily_answer[:500]}\n\n"

    md += """## 四、引用原话

"""
    for r in (tier_groups.get("A", []) + tier_groups.get("B", []))[:4]:
        raw = r.get("_clean_content") or r.get("content", "")
        quotes = re.findall(r'[""「『]([^"」』]{20,200})[""」』]', raw)
        for q in quotes[:2]:
            md += f"> {q[:150]}\n> — {r.get('title','')[:40]}\n\n"

    md += """## 五、使用说明

1. **所有数据必须来自本素材包**，禁止捏造数字
2. **优先使用 A/B 级来源**，C 级仅作背景参考
3. 引用格式：`"原话" — 来源`
4. **如数据不足，换选题，不要凑合**
"""
    return md

# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="研究搜索 v2 — 生成写作素材包")
    parser.add_argument("--topic", required=True, help="选题核心关键词")
    parser.add_argument("--client", required=True, help="客户名")
    parser.add_argument("--output-dir", help="输出目录")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--save", help="保存路径")
    args = parser.parse_args()

    # 多角度搜索
    queries = [
        args.topic,
        f"{args.topic} 官方 声明",
        f"{args.topic} 投资 策略",
    ]

    all_results = []
    tavily_answer = ""
    for q in queries:
        results = search_tavily(q, max_results=args.max_results // len(queries) + 3)
        for r in results:
            if r not in all_results:
                all_results.append(r)
        if not tavily_answer and results:
            # 用第一条结果的 answer 作为综合结论
            tavily_answer = results[0].get("answer", "")

    if not all_results:
        print("Warning: No results", file=sys.stderr)
        sys.exit(1)

    # 去重 + 分级
    ranked = rank_and_dedup(all_results)

    # 生成素材包
    pkg = build_materials_package(args.topic, ranked, tavily_answer)

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(pkg, encoding="utf-8")
        print(f"✅ 素材包已保存: {args.save}")

    print(pkg)

if __name__ == "__main__":
    main()
