#!/usr/bin/env python3
"""
audit_gaps.py — 审计 poetry.yaml vs history.yaml 的诗池缺口

用法：
  python3 audit_gaps.py            # 列出全部缺口（priority >= 5）
  python3 audit_gaps.py --min 7    # 只看 priority >= 7 的缺口
  python3 audit_gaps.py --top 3    # 只看前 3 个推荐（按 yaml 顺序）
  python3 audit_gaps.py --json     # 输出 JSON 格式

依赖：
  - poetry.yaml: 选题池（按优先级）
  - history.yaml: 已发布历史
  - output/mine/**/*.md: 实际生成的文件
"""
import argparse
import json
import os
import re
import sys
import glob
import yaml
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent
POOL_PATH = SKILL_DIR / 'clients' / 'mine' / 'topic-pools' / 'poetry.yaml'
HIST_PATH = SKILL_DIR / 'clients' / 'mine' / 'history.yaml'
OUTPUT_GLOB = str(SKILL_DIR / 'output' / 'mine' / '**' / '*.md')

# ── 拼音 slug → 完整标题 映射 ────────────────────────────────────────────
SLUG_TO_TITLE = {
    'wang-lushan-pulu': '望庐山瀑布',
    'chunwang': '春望',
    'fu-de-gu-yuan-cao-song-bie': '赋得古原草送别',
    'shuidiao-getou': '水调歌头·明月几时有',
    'shizhi-saishang': '使至塞上',
    'sheng-sheng-man': '声声慢·寻寻觅觅',
    'qing-yu-an-yuan-xi': '青玉案·元夕',
    'nian-nu-jiao': '念奴娇·赤壁怀古',
    'ding-feng-bo': '定风波·莫听穿林打叶声',
    'yin-hu-shang': '饮湖上初晴后雨',
    'du-guan-qiao-lou': '登鹳雀楼',
    'chun-jiang-hua-yue-ye': '春江花月夜',
    'you-zi-yin': '游子吟',
    'min-nong': '悯农·其二',
    'yu-mei-ren': '虞美人·春花秋月何时了',
    'tian-jing-sha-qiu-si': '天净沙·秋思',
    'shu-dao-nan': '蜀道难',
    'xing-lu-nan': '行路难·其一',
    'mao-wu': '茅屋为秋风所破歌',
    'jiang-cheng-zi-yi-miao': '江城子·乙卯正月二十日夜记梦',
    'ti-xi-lin-bi': '题西林壁',
    'bi-pa-xing': '琵琶行',
    'qian-tang-hu-chun-xing': '钱塘湖春行',
    'die-lian-hua-chun-jing': '蝶恋花·春景',
    'song-yuan-er-shi-an-xi': '送元二使塞上',
    'wang-yue': '望岳',
    'chun-ye-xi-yu': '春夜喜雨',
    'ru-meng-ling': '如梦令·常记溪亭日暮',
    'yi-jian-mei-hong-ou': '一剪梅·红藕香残玉簟秋',
    'po-zhen-zi': '破阵子·为陈同甫赋壮词以寄',
    'xi-jiang-yue-ye-xing': '西江月·夜行黄沙道中',
    'feng-qiao-ye-bo': '枫桥夜泊',
    'qing-ming': '清明',
    'shan-xing': '山行',
    'jiang-cheng-zi-mi-zhou': '江城子·密州出猎',
}


def collect_done_titles() -> set:
    """从 history.yaml + output/ 目录收集已写过的诗名"""
    done = set()

    # 1. history.yaml 的 poem 字段
    if HIST_PATH.exists():
        with open(HIST_PATH) as f:
            hist = f.read()
        for t in re.findall(r'poem: "([^"]+)"', hist):
            done.add(t)

    # 2. output/mine/ 目录的文件名匹配
    for f in glob.glob(OUTPUT_GLOB, recursive=True):
        bn = os.path.basename(f)
        if any(k in bn.lower() for k in ('cover', 'preview', 'research')):
            continue
        base = bn.replace('.md', '').lower()

        matched = False
        for slug, title in SLUG_TO_TITLE.items():
            if slug in base:
                done.add(title)
                matched = True
                break

        if not matched:
            # 中文标题直接匹配（文件名为 标题_日期.md）
            m = re.match(r'(.+?)_\d{4}-\d{2}-\d{2}', base)
            if m:
                done.add(m.group(1).strip())

    return done


def audit_gaps(min_priority: int = 5) -> list:
    """返回缺口列表，按 (priority 降序, yaml 顺序) 排序"""
    with open(POOL_PATH) as f:
        data = yaml.safe_load(f)
    poems = data['poems']
    done = collect_done_titles()

    gaps = []
    for p in poems:
        pri = p.get('priority', 0)
        if pri < min_priority:
            continue
        if p['title'] in done:
            continue
        gaps.append({
            'title': p['title'],
            'author': p['author'],
            'dynasty': p.get('dynasty', ''),
            'priority': pri,
            'difficulty': p.get('difficulty', '?'),
            'reason': p.get('reason', ''),
        })

    return gaps


def main():
    parser = argparse.ArgumentParser(description='诗池缺口审计')
    parser.add_argument('--min', type=int, default=5,
                        help='最低 priority（默认 5）')
    parser.add_argument('--top', type=int, default=0,
                        help='只看前 N 个缺口（默认全部）')
    parser.add_argument('--json', action='store_true',
                        help='输出 JSON 格式')
    args = parser.parse_args()

    gaps = audit_gaps(args.min)

    if args.top > 0:
        gaps = gaps[:args.top]

    if args.json:
        print(json.dumps(gaps, ensure_ascii=False, indent=2))
        return

    # 人类可读输出
    if not gaps:
        print('✅ 无缺口！所有 priority >= {} 的诗都已写完。'.format(args.min))
        return

    by_pri = {}
    for g in gaps:
        by_pri.setdefault(g['priority'], []).append(g)

    print('=== 诗池缺口审计 ===\n')
    for pri in sorted(by_pri.keys(), reverse=True):
        items = by_pri[pri]
        print(f'priority {pri}: {len(items)} 首待写')
        for g in items:
            print(f'  ❌ {g["title"]} ({g["author"]}, 难度 {g["difficulty"]})')

    print(f'\n总缺口: {len(gaps)} 首')
    if gaps:
        print(f'\n推荐下一首（priority 最高 + yaml 顺序最前）:')
        print(f'  → 《{gaps[0]["title"]}》({gaps[0]["author"]}, 难度 {gaps[0]["difficulty"]})')


if __name__ == '__main__':
    main()
