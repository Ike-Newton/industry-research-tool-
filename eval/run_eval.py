"""字段级评测：规则模式 vs 模型模式。

为什么要写这个：
"能跑通"和"抽得准"是两件事。没有评测集，你无法回答"这个工具准不准"，
也无法判断改一次 prompt 到底是变好还是变坏。

用法：
  python eval/run_eval.py            # 评测规则模式（不需要 API key）
  python eval/run_eval.py --llm      # 评测模型模式（需要 LLM_API_KEY）
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tasks  # noqa: E402

LABELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels.jsonl")
FIELDS = ["company", "industry", "round", "amount", "investors", "date"]


def norm(v) -> str:
    """比较前的归一化：只做格式层面的等价（空格、月/日/号、全角），不改语义。"""
    if v is None:
        return ""
    s = str(v).strip()
    s = re.sub(r"\s+", "", s)
    s = s.replace("（", "(").replace("）", ")").replace("，", ",")
    s = re.sub(r"[月日号]$", "", s)
    return s


def load_labels() -> list:
    rows = []
    with open(LABELS, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def evaluate(use_llm: bool) -> int:
    rows = load_labels()
    hits = {f: 0 for f in FIELDS}
    misses = []

    for i, row in enumerate(rows, 1):
        if use_llm:
            got = tasks.run_industry(row["text"], offline=False)["events"]
            pred = got[0] if got else {}
        else:
            pred = tasks.industry_offline(row["text"])["events"]
            pred = pred[0] if pred else {}
        for f in FIELDS:
            if norm(pred.get(f)) == norm(row["expected"].get(f)):
                hits[f] += 1
            else:
                misses.append((i, f, row["expected"].get(f), pred.get(f)))

    total = len(rows) * len(FIELDS)
    ok = sum(hits.values())
    mode = "模型模式" if use_llm else "规则模式"

    print("== %s · 字段级评测 ==" % mode)
    print("样本数：%d 条事件，%d 个字段" % (len(rows), total))
    for f in FIELDS:
        print("  %-10s %2d/%2d  %5.1f%%" % (f, hits[f], len(rows), 100.0 * hits[f] / len(rows)))
    print("  %-10s %2d/%2d  %5.1f%%" % ("整体", ok, total, 100.0 * ok / total))

    if misses:
        print("\n== 抽错的字段（这是下一步要改的地方）==")
        for i, f, want, got in misses:
            print("  第 %d 条 %-9s 期望=%r 实际=%r" % (i, f, want, got))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="评测模型模式")
    a = ap.parse_args()
    sys.exit(evaluate(a.llm))
