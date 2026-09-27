"""用量：python main.py "智能驾驶" --input sample_input.txt
      python main.py "智能驾驶" --text "示例公司A宣布完成A轮融资……" --feishu

输出：output.csv（公司/行业/轮次/金额/投资方/日期/来源）
"""
import argparse
import csv
import os
import sys

from extract import FIELDS, extract

try:
    from feishu import send_text
except Exception:  # pragma: no cover
    send_text = None


def load_text(args) -> str:
    if args.text:
        return args.text
    with open(args.input, "r", encoding="utf-8") as f:
        return f.read()


def to_csv(rows: list, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in FIELDS})


def render(rows: list) -> str:
    lines = ["共抽取 %d 条事件：" % len(rows)]
    for i, r in enumerate(rows, 1):
        bits = " | ".join(str(r.get(k) or "-") for k in FIELDS)
        lines.append("%d. %s" % (i, bits))
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="融资事件结构化抽取")
    p.add_argument("keyword", nargs="?", default="", help="赛道关键词（用于报告标题）")
    p.add_argument("--input", default="sample_input.txt", help="输入文本文件")
    p.add_argument("--text", default="", help="直接给一段文本，优先于 --input")
    p.add_argument("--out", default="output.csv", help="输出 CSV 路径")
    p.add_argument("--offline", action="store_true", help="不调模型，走规则模式")
    p.add_argument("--feishu", action="store_true", help="把结果发到飞书群机器人")
    args = p.parse_args()

    text = load_text(args)
    rows = extract(text, offline=args.offline)
    to_csv(rows, args.out)

    report = "[%s] %s" % (args.keyword or "未指定赛道", render(rows))
    print(report)
    print("\n已写出：" + os.path.abspath(args.out))

    if args.feishu:
        if send_text is None:
            print("飞书模块不可用", file=sys.stderr)
            return 2
        send_text(report)
        print("已推送飞书")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
