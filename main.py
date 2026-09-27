"""投研小工具 · 命令行入口

三个动作，每个都对应投研同事日常的一句抱怨：
  industry  找资料 → 把一堆报道变成结构化的融资事件表
  digest    看材料 → 把长文档压成要点 / 数据 / 风险 / 待确认
  minutes   开会   → 把转写整理成决议 / 待办 / 责任人 / 时间

用法：
  python main.py industry --input samples/industry_news.txt
  python main.py minutes  --input samples/meeting_transcript.txt --feishu
  python main.py digest   --text "把材料粘在这里"
  加 --offline 可在没有 API key 时跑通流程（规则模式，质量较低）
"""
import argparse
import csv
import json
import os
import sys

import feishu
import llm
import tasks

OUT_DIR = "out"

# Windows 控制台默认是 GBK：文本里出现 BOM、生僻字或 emoji 时，print 本身就会抛
# UnicodeEncodeError 把程序打断。这里强制 UTF-8 输出，无法编码的字符降级替换。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 依次尝试：带 BOM 的 UTF-8 → 普通 UTF-8 → GBK/GB18030（Windows 记事本"ANSI"就是这个）
READ_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


class InputError(RuntimeError):
    """输入不可用（文件缺失 / 编码识别不了），消息直接给用户看。"""


def _read_text(args) -> str:
    if args.text:
        return args.text
    path = args.input
    if not os.path.exists(path):
        raise InputError("找不到输入文件：%s（检查路径，或用 --text 直接传一段文本）" % path)

    raw = open(path, "rb").read()
    for enc in READ_ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InputError("无法识别文件编码：%s（支持 UTF-8 / UTF-8-BOM / GBK）" % path)


# ---------------------------------------------------------------- 渲染

def render_industry(result: dict) -> tuple:
    events = result["events"]
    lines = ["共 %d 条融资事件（%s）" % (len(events), result.get("_mode"))]
    for i, e in enumerate(events, 1):
        lines.append("%d. %s | %s | %s | %s | %s | %s" % (
            i, e.get("company") or "-", e.get("industry") or "-", e.get("round") or "-",
            e.get("amount") or "-", e.get("investors") or "-", e.get("date") or "-"))
    return "\n".join(lines), ["**共 %d 条融资事件**" % len(events)] + [
        "- %s ｜ %s ｜ %s" % (e.get("company") or "-", e.get("round") or "-", e.get("amount") or "-")
        for e in events[:20]]


def render_digest(result: dict) -> tuple:
    parts = ["摘要：" + (result.get("summary") or "-"), "", "要点："]
    parts += ["- " + p for p in result.get("points", [])]
    if result.get("metrics"):
        parts += ["", "数据点："] + ["- " + m for m in result["metrics"]]
    if result.get("risks"):
        parts += ["", "风险："] + ["- " + r for r in result["risks"]]
    if result.get("open_questions"):
        parts += ["", "待确认："] + ["- " + q for q in result["open_questions"]]
    return "\n".join(parts), ["**摘要**", result.get("summary") or "-"] + \
        ["**要点**"] + ["- " + p for p in result.get("points", [])[:6]]


def render_minutes(result: dict) -> tuple:
    parts = []
    if result.get("topics"):
        parts += ["议题："] + ["- " + t for t in result["topics"]] + [""]
    if result.get("decisions"):
        parts += ["决议："] + ["- " + d for d in result["decisions"]] + [""]
    if result.get("actions"):
        parts += ["待办："]
        for a in result["actions"]:
            parts.append("- %s ｜ 负责人：%s ｜ 时间：%s"
                         % (a.get("task"), a.get("owner") or "未指定", a.get("due") or "未指定"))
        parts.append("")
    if result.get("risks"):
        parts += ["风险："] + ["- " + r for r in result["risks"]]
    return "\n".join(parts), ["**待办 %d 条**" % len(result.get("actions", []))] + [
        "- %s（%s / %s）" % (a.get("task"), a.get("owner") or "未指定", a.get("due") or "未指定")
        for a in result.get("actions", [])[:10]]


RENDERERS = {"industry": render_industry, "digest": render_digest, "minutes": render_minutes}


def write_csv(events: list, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tasks.EVENT_FIELDS)
        w.writeheader()
        for e in events:
            w.writerow({k: ("" if e.get(k) is None else e.get(k)) for k in tasks.EVENT_FIELDS})


def main() -> int:
    p = argparse.ArgumentParser(description="投研小工具（飞书 + 大模型）")
    p.add_argument("task", choices=sorted(tasks.TASKS), help="industry / digest / minutes")
    p.add_argument("--input", default="", help="输入文本文件")
    p.add_argument("--text", default="", help="直接给一段文本（优先于 --input）")
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--offline", action="store_true", help="不调模型，规则模式跑通流程")
    p.add_argument("--feishu", action="store_true", help="把结果推到飞书群")
    p.add_argument("--json", action="store_true", help="同时输出原始 JSON")
    args = p.parse_args()

    if not args.text and not args.input:
        p.error("需要 --input 或 --text")

    try:
        text = _read_text(args)
    except InputError as e:
        print("错误：" + str(e), file=sys.stderr)
        return 2

    if not args.offline and not llm.has_api_key():
        print("提示：未检测到 LLM_API_KEY，已自动改用规则模式（抽取质量低于模型模式）。"
              "要调模型请先设置 LLM_API_KEY。", file=sys.stderr)

    try:
        result = tasks.TASKS[args.task](text, offline=args.offline)
    except llm.LLMError as e:
        print("模型调用失败：" + str(e), file=sys.stderr)
        print("可以先加 --offline 用规则模式确认流程跑通。", file=sys.stderr)
        return 4
    body, card_lines = RENDERERS[args.task](result)

    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.join(args.out_dir, args.task)
    wrote = [base + ".txt"]
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(body + "\n")
    if args.json or args.task == "industry":
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        wrote.append(base + ".json")
    if args.task == "industry":
        write_csv(result["events"], base + ".csv")
        wrote.append(base + ".csv")

    print(body)
    print("\n已写出：" + "、".join(os.path.abspath(x) for x in wrote))

    if args.feishu:
        try:
            feishu.send_card("%s｜%s" % (args.task, "规则模式" if args.offline else "模型模式"), card_lines)
        except feishu.FeishuError as e:
            print("飞书推送失败：" + str(e), file=sys.stderr)
            print("（结果已写入本地文件，不影响使用）", file=sys.stderr)
            return 3
        print("已推送飞书")
    return 0


if __name__ == "__main__":
    sys.exit(main())
