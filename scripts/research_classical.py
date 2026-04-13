#!/usr/bin/env python3
"""
research_classical.py — 古诗词/生僻字权威查证脚本

用法：
  python3 research_classical.py --type poetry --title "静夜思" --author "李白"
  python3 research_classical.py --type character --char "㐂"
  python3 research_classical.py --type word --phrase "春江水暖鸭先知"
"""

import argparse
import sys
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

# Jina Reader API — 干净提取网页内容（绕过广告/噪音）
JINA_READER = "https://r.jina.ai/http://{url}"

# 权威信源列表（按优先级）
POETRY_SOURCES = [
    ("古诗词网", "https://www.gushiwen.cn/default.aspx"),
    ("诗词名句网", "https://www.shicimingju.com"),
]

CHAR_SOURCES = [
    ("汉典", "https://www.zdic.net"),
    ("古诗词网", "https://www.gushiwen.cn/default.aspx"),
]

WORD_SOURCES = [
    ("诗词名句网", "https://www.shicimingju.com"),
    ("汉典", "https://www.zdic.net"),
]


@dataclass
class SourceResult:
    name: str
    url: str
    content: str = ""
    success: bool = False
    is_ai_fallback: bool = False


@dataclass
class WritingMaterial:
    title: str
    author: str = ""
    item_type: str = ""

    # 原始数据
    raw_content: dict = field(default_factory=dict)

    # 输出结构
    grade_a: list = field(default_factory=list)  # 已核实，直接可用
    grade_b: list = field(default_factory=list)  # 参考，需人工核实
    key_points: list = field(default_factory=list)  # 关键数据点
    citations: list = field(default_factory=list)  # 引用标注
    warnings: list = field(default_factory=list)  # 警告信息


def fetch_jina(url: str, timeout: float = 3.0) -> Optional[str]:
    """使用 Jina Reader API 干净提取网页内容，3秒超时。"""
    import urllib.request
    import urllib.error

    reader_url = JINA_READER.format(url=url)
    try:
        req = urllib.request.Request(
            reader_url,
            headers={
                "Accept": "text/plain",
                "X-Timeout": str(int(timeout)),
                "User-Agent": "Mozilla/5.0 (compatible; research_classical/1.0)",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def build_poetry_search_url(title: str, author: str = "") -> str:
    """构建古诗词搜索 URL。"""
    if author:
        q = f"{title} {author}"
    else:
        q = title
    encoded = urllib.parse.quote(q)
    return f"https://www.gushiwen.cn/search?value={encoded}"


def build_poem_page_url(title: str, author: str = "") -> str:
    """构建古诗词网诗词详情页 URL（猜测路径）。"""
    # 古诗词网使用 ID 路由，直接搜索更可靠
    return build_poetry_search_url(title, author)


def build_character_url(char: str) -> str:
    """构建汉典字形查询 URL。"""
    encoded = urllib.parse.quote(char)
    return f"https://www.zdic.net/hans/{encoded}"


def build_word_search_url(phrase: str) -> str:
    """构建诗词名句网搜索 URL。"""
    encoded = urllib.parse.quote(phrase)
    return f"https://www.shicimingju.com/search?search={encoded}"


def extract_poetry_from_gushiwen(content: str) -> dict:
    """从古诗词网内容中提取诗词信息。"""
    data = {
        "title": "",
        "author": "",
        "dynasty": "",
        "content": [],
        "translation": "",
        "notes": [],
        "appreciation": "",
    }

    lines = content.split("\n")
    # 尝试匹配标题行（通常是大字）
    # 匹配诗词正文：常见五言/七言格式
    poetry_lines = []
    in_translation = False
    in_notes = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检测标题（无标点或只有一个书名号）
        if not data["title"] and re.match(r"^《[^》]+》$", line):
            data["title"] = line.strip("《》")

        # 检测朝代/作者
        if re.match(r"^(唐|宋|元|明|清|南北朝|隋|晋|汉|魏)代?", line):
            data["dynasty"] = line
        if re.match(r"^[A-Za-z\u4e00-\u9fa5]+$", line) and len(line) <= 6 and not data.get("author"):
            if "作者" not in line:
                data["author"] = line

        # 检测诗文正文（连续的短句）
        if re.match(r"^[\u4e00-\u9fa5]{5,7}[，、。！？；]$", line):
            poetry_lines.append(line)

        # 检测译文/注释标记
        if any(kw in line for kw in ["译文", "注释", "翻译", "赏析"]):
            in_translation = True
            in_notes = True

    if poetry_lines:
        data["content"] = poetry_lines

    return data


def extract_character_from_zdic(content: str) -> dict:
    """从汉典内容中提取字形、拼音、释义信息。"""
    data = {
        "character": "",
        "pinyin": "",
        "radical": "",
        "strokes": "",
        "definitions": [],
        "words": [],
        "evolution": "",
    }

    lines = content.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 拼音提取
        pinyin_match = re.findall(r"【拼音】\s*(.+)", line)
        if pinyin_match:
            data["pinyin"] = pinyin_match[0]

        # 部首
        radical_match = re.findall(r"【部首】\s*(.+)", line)
        if radical_match:
            data["radical"] = radical_match[0]

        # 笔画
        strokes_match = re.findall(r"【笔画】\s*(.+)", line)
        if strokes_match:
            data["strokes"] = strokes_match[0]

        # 释义
        def_match = re.findall(r"【释义】\s*(.+)", line)
        if def_match:
            data["definitions"].append(def_match[0])

    return data


def fetch_poetry(title: str, author: str = "") -> WritingMaterial:
    """查询古诗词信息。"""
    material = WritingMaterial(title=title, author=author, item_type="poetry")
    results = []

    # 策略1: 古诗词网搜索
    search_url = build_poetry_search_url(title, author)
    content = fetch_jina(search_url, timeout=3.0)
    if content:
        data = extract_poetry_from_gushiwen(content)
        if data["content"]:
            results.append(
                SourceResult(
                    name="古诗词网",
                    url=search_url,
                    content=content,
                    success=True,
                )
            )
            material.raw_content["gushiwen"] = data

    # 策略2: 诗词名句网
    word_url = build_word_search_url(title)
    content2 = fetch_jina(word_url, timeout=3.0)
    if content2:
        results.append(
            SourceResult(
                name="诗词名句网",
                url=word_url,
                content=content2,
                success=True,
            )
        )

    # 合并结果
    if results:
        material.grade_a.append({
            "source": results[0].name,
            "url": results[0].url,
            "data": material.raw_content.get("gushiwen", {}),
        })
        for r in results[1:]:
            material.grade_b.append({
                "source": r.name,
                "url": r.url,
                "content": r.content[:500],
            })
    else:
        material.warnings.append("⚠️ 所有权威信源均失败，使用 AI 知识补充，来源待考")
        material.grade_a.append({
            "source": "AI知识补充",
            "url": "",
            "data": _ai_poetry_fallback(title, author),
            "is_ai": True,
        })

    # 关键数据点
    _build_poetry_key_points(material)
    return material


def fetch_character(char: str) -> WritingMaterial:
    """查询生僻字信息。"""
    material = WritingMaterial(title=char, item_type="character")
    results = []

    # 策略1: 汉典
    char_url = build_character_url(char)
    content = fetch_jina(char_url, timeout=3.0)
    if content:
        data = extract_character_from_zdic(content)
        results.append(
            SourceResult(
                name="汉典",
                url=char_url,
                content=content,
                success=True,
            )
        )
        material.raw_content["zdic"] = data

    # 策略2: 古诗词网
    encoded_char = urllib.parse.quote(char)
    gushiwen_url = f"https://www.gushiwen.cn/search?value={encoded_char}"
    content2 = fetch_jina(gushiwen_url, timeout=3.0)
    if content2:
        results.append(
            SourceResult(
                name="古诗词网",
                url=gushiwen_url,
                content=content2,
                success=True,
            )
        )

    if results:
        material.grade_a.append({
            "source": results[0].name,
            "url": results[0].url,
            "data": material.raw_content.get("zdic", {}),
        })
        for r in results[1:]:
            material.grade_b.append({
                "source": r.name,
                "url": r.url,
                "content": r.content[:500],
            })
    else:
        material.warnings.append("⚠️ 所有权威信源均失败，使用 AI 知识补充，来源待考")
        material.grade_a.append({
            "source": "AI知识补充",
            "url": "",
            "data": _ai_character_fallback(char),
            "is_ai": True,
        })

    _build_character_key_points(material)
    return material


def fetch_word(phrase: str) -> WritingMaterial:
    """查询诗句/词组出处。"""
    material = WritingMaterial(title=phrase, item_type="word")
    results = []

    # 策略1: 诗词名句网
    word_url = build_word_search_url(phrase)
    content = fetch_jina(word_url, timeout=3.0)
    if content:
        results.append(
            SourceResult(
                name="诗词名句网",
                url=word_url,
                content=content,
                success=True,
            )
        )

    # 策略2: 汉典
    encoded_phrase = urllib.parse.quote(phrase)
    zdic_url = f"https://www.zdic.net/hans/?q={encoded_phrase}"
    content2 = fetch_jina(zdic_url, timeout=3.0)
    if content2:
        results.append(
            SourceResult(
                name="汉典",
                url=zdic_url,
                content=content2,
                success=True,
            )
        )

    if results:
        material.grade_a.append({
            "source": results[0].name,
            "url": results[0].url,
            "content": results[0].content[:800],
        })
        for r in results[1:]:
            material.grade_b.append({
                "source": r.name,
                "url": r.url,
                "content": r.content[:500],
            })
    else:
        material.warnings.append("⚠️ 所有权威信源均失败，使用 AI 知识补充，来源待考")
        material.grade_a.append({
            "source": "AI知识补充",
            "url": "",
            "data": {"phrase": phrase, "note": "来源待考"},
            "is_ai": True,
        })

    _build_word_key_points(material)
    return material


def _ai_poetry_fallback(title: str, author: str) -> dict:
    """AI 知识补充——古诗词（最后手段）。"""
    return {
        "title": title,
        "author": author,
        "note": "（AI知识补充，来源待考）",
        "disclaimer": "以下内容为 AI 知识补充，建议通过权威信源核实",
    }


def _ai_character_fallback(char: str) -> dict:
    """AI 知识补充——生僻字（最后手段）。"""
    codepoint = ord(char)
    return {
        "character": char,
        "unicode": f"U+{codepoint:04X}",
        "note": "（AI知识补充，来源待考）",
        "disclaimer": "以下内容为 AI 知识补充，建议通过权威信源核实",
    }


def _build_poetry_key_points(material: WritingMaterial):
    """构建古诗词关键数据点。"""
    data = material.raw_content.get("gushiwen", {})
    title = material.title
    author = material.author

    encoded_title = urllib.parse.quote(title)
    material.citations.append({
        "id": "[1]",
        "source": "古诗词网",
        "url": f"https://www.gushiwen.cn/search?value={encoded_title}",
    })

    # 标题、作者
    if data.get("title"):
        material.key_points.append({
            "point": f"诗题：{data['title']}",
            "source": "[1]",
        })
    if data.get("author"):
        material.key_points.append({
            "point": f"作者：{data['author']}（{data.get('dynasty', '未知')}）",
            "source": "[1]",
        })
    if data.get("content"):
        content_str = "；".join(data["content"])
        material.key_points.append({
            "point": f"诗文：{content_str}",
            "source": "[1]",
        })
    if data.get("translation"):
        material.key_points.append({
            "point": f"译文：{data['translation'][:200]}",
            "source": "[1]",
        })


def _build_character_key_points(material: WritingMaterial):
    """构建生僻字关键数据点。"""
    data = material.raw_content.get("zdic", {})
    char = material.title
    encoded_char = urllib.parse.quote(char)

    material.citations.append({
        "id": "[1]",
        "source": "汉典",
        "url": f"https://www.zdic.net/hans/{encoded_char}",
    })

    if data.get("pinyin"):
        material.key_points.append({
            "point": f"拼音：{data['pinyin']}",
            "source": "[1]",
        })
    if data.get("radical"):
        material.key_points.append({
            "point": f"部首：{data['radical']}",
            "source": "[1]",
        })
    if data.get("strokes"):
        material.key_points.append({
            "point": f"笔画：{data['strokes']}",
            "source": "[1]",
        })
    if data.get("definitions"):
        for d in data["definitions"]:
            material.key_points.append({
                "point": f"释义：{d}",
                "source": "[1]",
            })


def _build_word_key_points(material: WritingMaterial):
    """构建词组关键数据点。"""
    encoded_phrase = urllib.parse.quote(material.title)
    material.citations.append({
        "id": "[1]",
        "source": "诗词名句网",
        "url": f"https://www.shicimingju.com/search?search={encoded_phrase}",
    })

    material.key_points.append({
        "point": f"词组/诗句：{material.title}",
        "source": "[1]",
    })


def format_markdown(material: WritingMaterial) -> str:
    """将素材格式化为 Markdown 写作素材包。"""
    lines = []
    lines.append(f"# 📚 写作素材包")
    lines.append("")
    lines.append(f"**类型：** {material.item_type}  |  **标题：** {material.title}  |  **作者：** {material.author or '未知'}")
    lines.append("")

    # 警告
    if material.warnings:
        for w in material.warnings:
            lines.append(w)
        lines.append("")

    # A级信源
    lines.append("## 🔵 A级信源（已核实，直接可用）")
    lines.append("")
    for i, item in enumerate(material.grade_a, 1):
        source = item.get("source", "")
        url = item.get("url", "")
        is_ai = item.get("is_ai", False)

        if is_ai:
            lines.append(f"**⚠️ {source}**（来源待考）")
        else:
            lines.append(f"**{source}**")
            if url:
                lines.append(f"来源：{url}")

        data = item.get("data", {})
        content = item.get("content", "")

        if data:
            if isinstance(data, dict):
                for k, v in data.items():
                    if v and k not in ("note", "disclaimer", "is_ai"):
                        lines.append(f"- **{k}**：{v}")
            else:
                lines.append(f"- {data}")
        elif content:
            lines.append(f"- {content[:300]}")

        lines.append("")

    # B级信源
    if material.grade_b:
        lines.append("## 🟡 B级信源（参考，需人工核实）")
        lines.append("")
        for item in material.grade_b:
            lines.append(f"**{item['source']}**：{item['url']}")
            lines.append(f"```\n{item['content'][:200]}...\n```")
            lines.append("")

    # 关键数据点
    lines.append("## 📌 关键数据点")
    lines.append("")
    for kp in material.key_points:
        lines.append(f"- {kp['point']} {kp['source']}")
    lines.append("")

    # 引用标注
    lines.append("## 📖 引用标注集合")
    lines.append("")
    for cit in material.citations:
        lines.append(f"{cit['id']} [{cit['source']}]：{cit['url']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="古诗词/生僻字权威查证脚本")
    parser.add_argument("--type", choices=["poetry", "character", "word"], required=True,
                        help="查询类型：poetry=古诗词, character=生僻字, word=词组/诗句")
    parser.add_argument("--title", help="诗词/词组标题（poetry/word 类型）")
    parser.add_argument("--author", help="作者（poetry 类型）")
    parser.add_argument("--char", help="查询的汉字（character 类型）")
    parser.add_argument("--phrase", help="查询的词组（word 类型）")
    args = parser.parse_args()

    if args.type == "poetry":
        if not args.title:
            print("错误：poetry 类型需要 --title 参数", file=sys.stderr)
            sys.exit(1)
        material = fetch_poetry(args.title, args.author or "")
    elif args.type == "character":
        if not args.char:
            print("错误：character 类型需要 --char 参数", file=sys.stderr)
            sys.exit(1)
        material = fetch_character(args.char)
    elif args.type == "word":
        if not args.phrase:
            print("错误：word 类型需要 --phrase 参数", file=sys.stderr)
            sys.exit(1)
        material = fetch_word(args.phrase)
    else:
        print(f"未知类型：{args.type}", file=sys.stderr)
        sys.exit(1)

    print(format_markdown(material))


if __name__ == "__main__":
    main()
