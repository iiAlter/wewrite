#!/usr/bin/env python3
"""
Step 3.2 — Research Search
搜索选题相关官方权威来源，生成结构化写作素材包。

优先级：
  A级（首选）：官方公告、政府网站、上市公司年报、官方机构
  B级（辅助）：央视、财新、36kr、澎湃
  C级（舆情参考）：知乎、微博热评（不作事实引用）

输出：写作素材包 Markdown，保存在 output/{client}/{date}-{slug}-research.md
"""

import argparse
import json
import os
import sys
import requests
import yaml
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────────────

CONFIG_PATHS = [
    Path.cwd() / "config.yaml",
    Path(__file__).parent.parent / "config.yaml",
    Path(__file__).parent.parent / "toolkit" / "config.py",
]

def load_config():
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}

ENV_KEYS = {
    "wechat": ("WEWRITE_WECHAT_APPID", "WEWRITE_WECHAT_SECRET"),
    "llm": ("WEWRITE_LLM_API_KEY",),
    "image": ("WEWRITE_IMAGE_API_KEY",),
}
cfg = load_config()
for section, keys in ENV_KEYS.items():
    if section not in cfg:
        cfg[section] = {}
    for key in keys:
        env_val = os.environ.get(key)
        if env_val:
            sec_key = key.replace("WEWRITE_", "").split("_", 1)[1].lower()
            cfg[section][sec_key] = env_val

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY") or cfg.get("llm", {}).get("api_key", "")
if not TAVILY_API_KEY:
    print("Error: TAVILY_API_KEY not set in env or config.yaml", file=sys.stderr)
    sys.exit(1)

TAVILY_URL = "https://api.tavily.com/search"

# ── Source Rankings ────────────────────────────────────────────────────────

# 可信度分级，A最高
SOURCE_TIERS = {
    "A": [
        "gov.cn", "gov.uk", "gov.au", "gov",
        "who.int", "imf.org", "worldbank.org",
        "sec.gov", "csrc.gov.cn", "sse.com.cn", "szse.cn",
        "uspto.gov", "euipo.europa.eu",
        "nbaa.org", "cfo.org",
        "xinhuanet.com", "people.com.cn", "gov.cn",
        "cma.gov.cn", "stats.gov.cn",
    ],
    "B": [
        "36kr.com", "caixin.com", "yicai.com", "cls.cn",
        "cctv.com", "thepaper.cn", "bjnews.com.cn",
        "reuters.com", "bloomberg.com", "ft.com",
        "wsj.com", "economist.com",
        "scmp.com", "nikkei.com",
    ],
    "C": [
        "zhihu.com", "weibo.com", "twitter.com", "x.com",
        "douban.com", "bilibili.com",
    ]
}

def rate_source(url: str) -> str:
    url_lower = url.lower()
    for tier in ["A", "B", "C"]:
        for domain in SOURCE_TIERS[tier]:
            if domain in url_lower:
                return tier
    return "C"  # 未知来源默认C

# ── Search ────────────────────────────────────────────────────────────────

def search_tavily(query: str, max_results: int = 10, search_depth: str = "advanced") -> list[dict]:
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": True,
        "include_raw_content": False,
        "include_images": False,
    }
    resp = requests.post(TAVILY_URL, json=payload, timeout=30)
    data = resp.json()
    if resp.status_code != 200:
        print(f"Tavily error: {data}", file=sys.stderr)
        return []
    return data.get("results", [])

def deduplicate_and_prioritize(results: list[dict]) -> list[dict]:
    """按可信度分级 + 相关性去重，同一件事保留最高可信度来源。"""
    seen = {}  # title关键词指纹 -> 最高分结果
    for r in results:
        tier = rate_source(r.get("url", ""))
        score = r.get("score", 0)
        # A=3, B=2, C=1 叠加相关性
        weighted = score * (3 if tier == "A" else 2 if tier == "B" else 1)
        key = r.get("title", "")[:30]  # 用标题前30字去重
        if key not in seen or weighted > seen[key]["weighted"]:
            seen[key] = {"r": r, "weighted": weighted, "tier": tier}
    # 排序：先A后B后C，同级按相关性
    ranked = sorted(seen.values(), key=lambda x: (-int(x["tier"] == "A") * 10 - int(x["tier"] == "B") * 5 - int(x["tier"] == "C"), -x["weighted"]))
    return [x["r"] for x in ranked]

def extract_facts(results: list[dict]) -> dict:
    """从搜索结果提取结构化事实。"""
    facts = []
    data_points = []
    stances = defaultdict(list)
    quotes = []
    sentiments = []

    for r in results:
        tier = rate_source(r.get("url", ""))
        source_mark = f"[{r.get('title', '来源')[:20]}]({r.get('url', '')}) | 可信度：{tier}"

        content = r.get("content", "")
        answer = r.get("answer", "")

        if answer:
            quotes.append(f"> {answer[:200]}... — {source_mark}")

        # 简单抽取数字数据（原始方法，后续可升级为LLM抽取）
        import re
        numbers = re.findall(r'[\d,]+(?:\.\d+)?%?(?:亿|万|元|人|次|年|月|日|点|%)?', content)
        if numbers and len(numbers) <= 5:
            for num in numbers[:3]:
                if len(num) > 2:
                    data_points.append(f"- {num} — {source_mark}")

        # 简单立场提取
        positive_markers = ["支持", "赞成", "积极", "利好", "好消息"]
        negative_markers = ["反对", "质疑", "担忧", "风险", "利空"]
        for marker in positive_markers:
            if marker in content:
                stances["正方/官方"].append(f"- {marker}：{content[:100]}... — {source_mark}")
                break
        for marker in negative_markers:
            if marker in content:
                stances["质疑方/民间"].append(f"- {marker}：{content[:100]}... — {source_mark}")
                break

    return {
        "facts": list(dict.fromkeys(facts))[:10],
        "data_points": list(dict.fromkeys(data_points))[:10],
        "stances": dict(stances),
        "quotes": quotes[:5],
    }

def generate_materials_package(topic: str, results: list[dict], client: str, slug: str) -> str:
    """生成 Markdown 格式的写作素材包。"""
    tier_groups = defaultdict(list)
    for r in results:
        tier = rate_source(r.get("url", ""))
        tier_groups[tier].append(r)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    md = f"""# 写作素材包

> 生成时间：{now} | 选题：{topic} | 来源数：{len(results)}

## 核心事实（A级来源优先）

"""
    a_results = tier_groups.get("A", [])
    b_results = tier_groups.get("B", [])
    other_results = [r for r in results if r not in a_results and r not in b_results]

    for r in a_results[:5]:
        md += f"- {r.get('title', '')}：{r.get('content', '')[:150]}...\n  — [{r.get('url', '')}]({r.get('url', '')}) | 可信度：A\n\n"

    md += "\n## 关键数据\n\n"
    for r in (a_results + b_results)[:8]:
        import re
        content = r.get("content", "")
        numbers = re.findall(r'[\d,]+(?:\.\d+)?%?(?:亿|万|元|人|次|年|月|日|点|%)?', content)
        for num in numbers[:2]:
            if len(num) > 2:
                md += f"- **{num}** — {r.get('title', '')[:30]} | [来源]({r.get('url', '')}) | 可信度：{rate_source(r.get('url', ''))}\n"
    md += "\n## 各方立场\n\n"

    stances = extract_facts(results)["stances"]
    if stances:
        for label, items in stances.items():
            md += f"### {label}\n"
            md += "\n".join(items[:3]) + "\n\n"
    else:
        md += "_（从搜索结果中未提取到明确立场分化）_\n\n"

    md += "## 引用素材\n\n"
    for r in (a_results + b_results)[:5]:
        if r.get("answer"):
            md += f"> {r.get('answer', '')[:200]}\n> — [{r.get('title', '')}]({r.get('url', '')}) | 可信度：{rate_source(r.get('url', ''))}\n\n"

    md += """## 使用说明

1. 所有事实和数据必须来自本素材包，禁止捏造数字
2. 引用格式：`"原话" — 来源`
3. 区分事实陈述与观点陈述，不要混为一谈
4. 若素材包信息不足以支撑论点，宁可换选题，不要凑合
"""
    return md

# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="研究搜索：生成写作素材包")
    parser.add_argument("--topic", required=True, help="选题核心关键词")
    parser.add_argument("--client", required=True, help="客户名")
    parser.add_argument("--output-dir", help="输出目录（默认 output/{client}）")
    parser.add_argument("--max-results", type=int, default=10, help="搜索结果数（默认10）")
    parser.add_argument("--save", help="保存素材包到指定路径")
    args = parser.parse_args()

    slug = args.topic.replace(" ", "-")[:30]

    # 多角度搜索
    queries = [
        args.topic,
        f"{args.topic} 官方 声明",
        f"{args.topic} 最新 动态",
    ]

    all_results = []
    for q in queries:
        results = search_tavily(q, max_results=args.max_results // len(queries) + 2)
        all_results.extend(results)

    # 去重+分级
    deduped = deduplicate_and_prioritize(all_results)

    if not deduped:
        print("Warning: No results found", file=sys.stderr)
        sys.exit(1)

    # 生成素材包
    pkg = generate_materials_package(args.topic, deduped, args.client, slug)

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(pkg, encoding="utf-8")
        print(f"素材包已保存: {args.save}")

    print(pkg)

if __name__ == "__main__":
    main()
