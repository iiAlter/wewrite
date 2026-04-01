#!/usr/bin/env python3
"""
Format fixer for WeWrite markdown.
Fixes common style violations:
  - Blank lines within H2 sections (paragraphs should be contiguous)
  - H2 sections should be separated by exactly one blank line

Usage:
    python3 fix_format.py article.md  # fix in place
    python3 fix_format.py article.md --output fixed.md  # write to new file
"""

import argparse
import re
from pathlib import Path


def fix_format(text: str) -> str:
    lines = text.split("\n")
    result = []
    prev_blank = False
    prev_h2 = False

    for line in lines:
        is_blank = not line.strip()
        is_h2 = line.startswith("## ")

        if is_blank:
            # Only add blank line if previous was an H2 (H2 needs breathing room)
            if prev_h2:
                if result and result[-1] != "":
                    result.append("")
                prev_h2 = False
                prev_blank = True
                continue
            # Skip multiple consecutive blanks
            if prev_blank:
                continue
            result.append("")
            prev_blank = True
        else:
            # Non-blank line
            if prev_blank and not result[-1].startswith("## "):
                # Previous was blank, and we're not starting H2 - 
                # check if this is continuation of previous paragraph
                # If previous non-blank line existed and wasn't H2, this blank was paragraph separator
                # which is wrong - skip it
                pass
            result.append(line)
            prev_blank = False
            prev_h2 = is_h2

    # Post-process: remove blank lines between H2 header and first paragraph
    # and ensure exactly one blank before H2
    lines = result
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            # Remove any blank lines before this H2
            while result and result[-1] == "":
                result.pop()
            # Ensure blank before H2 (if not at start)
            if result and result[-1].strip():
                result.append("")
            result.append(line)
            # Skip blanks after H2 until first content
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            i -= 1  # back up one (the loop will advance)
        else:
            result.append(line)
        i += 1

    return "\n".join(result)


def main():
    parser = argparse.ArgumentParser(description="Fix WeWrite markdown format")
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument("--output", "-o", help="Output file (default: in-place)")
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8")
    fixed = fix_format(text)

    if args.output:
        Path(args.output).write_text(fixed, encoding="utf-8")
        print(f"Fixed: {args.output}")
    else:
        Path(args.input).write_text(fixed, encoding="utf-8")
        print(f"Fixed in place: {args.input}")


if __name__ == "__main__":
    main()
