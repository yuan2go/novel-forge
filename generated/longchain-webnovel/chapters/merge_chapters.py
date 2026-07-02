#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将当前目录下的单章小说文件，按章节编号排序后，每 n 章合并成一个文件。

默认：
- 当前目录读取 .md 文件
- 每 10 章合并为一个文件
- 输出到 merged_output 目录

用法：
python3 merge_chapters.py
python3 merge_chapters.py -n 20
python3 merge_chapters.py --ext .txt
python3 merge_chapters.py -n 10 --output merged_books
"""

import argparse
import re
from pathlib import Path
from typing import List, Optional, Tuple


def extract_chapter_number(file_path: Path) -> Optional[int]:
    """
    从文件名中提取章节编号。

    支持：
    chapter_001.md
    chapter-001.md
    第001章.md
    001.md
    001_xxx.md
    """

    name = file_path.stem

    patterns = [
        r"chapter[_-]?(\d+)",
        r"第\s*(\d+)\s*章",
        r"^(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


def find_chapter_files(current_dir: Path, ext: str) -> List[Tuple[int, Path]]:
    """
    查找当前目录下的章节文件，并按章节编号排序。
    """

    chapter_files = []

    for file_path in current_dir.iterdir():
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() != ext.lower():
            continue

        # 排除脚本生成的合并文件
        if file_path.name.startswith("merged_"):
            continue

        chapter_number = extract_chapter_number(file_path)
        if chapter_number is None:
            continue

        chapter_files.append((chapter_number, file_path))

    chapter_files.sort(key=lambda item: item[0])
    return chapter_files


def read_text(file_path: Path) -> str:
    """
    读取文本，优先使用 utf-8。
    """

    encodings = ["utf-8", "utf-8-sig", "gb18030"]

    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    raise UnicodeDecodeError(
        "unknown",
        b"",
        0,
        1,
        f"无法识别文件编码：{file_path}"
    )


def merge_group(group: List[Tuple[int, Path]], output_dir: Path) -> Path:
    """
    合并一组章节文件。
    """

    start_no = group[0][0]
    end_no = group[-1][0]

    output_file = output_dir / f"merged_{start_no:03d}_{end_no:03d}.md"

    parts = [
        f"# 合并稿：第{start_no:03d}章—第{end_no:03d}章",
        "",
    ]

    for chapter_no, file_path in group:
        content = read_text(file_path).strip()

        parts.append(f"\n\n---\n\n")
        parts.append(f"<!-- source: {file_path.name} -->\n\n")
        parts.append(content)
        parts.append("\n")

    output_file.write_text("\n".join(parts), encoding="utf-8")
    return output_file


def merge_chapters(n: int, ext: str, output: str) -> None:
    """
    主流程：按 n 章一组合并。
    """

    current_dir = Path.cwd()
    output_dir = current_dir / output
    output_dir.mkdir(parents=True, exist_ok=True)

    chapter_files = find_chapter_files(current_dir, ext)

    if not chapter_files:
        print(f"未找到章节文件。请确认当前目录下存在 {ext} 文件，并且文件名包含章节编号。")
        return

    print(f"找到 {len(chapter_files)} 个章节文件。")
    print(f"每 {n} 章合并为一个文件。")
    print(f"输出目录：{output_dir}")

    generated_files = []

    for i in range(0, len(chapter_files), n):
        group = chapter_files[i:i + n]
        output_file = merge_group(group, output_dir)
        generated_files.append(output_file)
        print(f"已生成：{output_file.name}")

    print("\n完成。")
    print(f"共生成 {len(generated_files)} 个合并文件。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将当前目录下的单章小说文件，按 n 章合并成多个文件。"
    )

    parser.add_argument(
        "-n",
        "--number",
        type=int,
        default=10,
        help="每个合并文件包含的章节数量，默认 10。"
    )

    parser.add_argument(
        "--ext",
        type=str,
        default=".md",
        help="章节文件扩展名，默认 .md。也可使用 .txt。"
    )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="merged_output",
        help="输出目录，默认 merged_output。"
    )

    args = parser.parse_args()

    if args.number <= 0:
        raise ValueError("参数 n 必须大于 0。")

    if not args.ext.startswith("."):
        args.ext = "." + args.ext

    merge_chapters(
        n=args.number,
        ext=args.ext,
        output=args.output,
    )


if __name__ == "__main__":
    main()
