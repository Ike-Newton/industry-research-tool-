"""三个投研场景任务：行业信息整理 / 文档摘要 / 会议纪要结构化。

每个任务都有两条路径：
- 模型路径：把要求写进 prompt，要求只输出 JSON（真正的能力在这里）
- 规则路径（offline）：正则/关键词启发式，**只用来在没有 key 时验证流程跑通**
  抽取质量明显低于模型路径，README 与评测脚本里都如实标注。
"""
import re

import llm

# ---------------------------------------------------------------- 任务 1：行业信息

EVENT_FIELDS = ["company", "industry", "round", "amount", "investors", "date", "source"]

INDUSTRY_PROMPT = """你是投资机构的数据整理助手。请从下面的文本中抽取所有**融资事件**，输出 JSON。

输出格式：{{"events": [{{"company": ..., "industry": ..., "round": ..., "amount": ...,
"investors": ..., "date": ..., "source": ...}}]}}

规则：
1. 只输出 JSON，不要任何解释文字，不要 Markdown 代码围栏。
2. 缺失字段填 null，不要猜。
3. amount 一律**保留原文**（如"数千万人民币""近亿元""未披露"），**不要做任何单位换算**。
4. 文本里有多条事件就输出多条。
5. investors 是字符串（多家机构用、连接），不要拆成数组。

文本：
{text}"""

ROUND_RE = re.compile(r"(天使轮|种子轮|Pre-?A\+?轮|A\+?轮|B\+?轮|C\+?轮|D\+?轮|战略融资|并购)")
AMOUNT_RE = re.compile(
    r"((?:近|超|约|逾)?\s*(?:[\d.]+\s*[亿万千万百万]+|数[亿万千万百万]+|"
    r"[一二三四五六七八九十]+[亿万千万百万]+|[亿万千万百万]+)\s*(?:元|美元|人民币)?|未披露)"
)
DATE_RE = re.compile(r"(20\d{2}\s*[-/年]\s*\d{1,2}(?:\s*[-/月]\s*\d{1,2}\s*日?)?)")
INDUSTRY_RE = re.compile(r"[（(]([^）)]{2,12})[）)]")
INVESTOR_RE = re.compile(r"(?:投资方|由|领投方|跟投方)(?:为|是)?\s*([^，,。；;]{2,40})")


def industry_offline(text: str) -> dict:
    events = []
    for line in re.split(r"[。\n]", text):
        line = line.strip()
        if not line or line.startswith(("注意", "#")):
            continue
        round_m = ROUND_RE.search(line)
        if not round_m:
            continue
        amount_m = AMOUNT_RE.search(line)
        date_m = DATE_RE.search(line)
        industry_m = INDUSTRY_RE.search(line)
        investor_m = INVESTOR_RE.search(line)

        company = re.split(r"[（(]", line)[0]
        company = re.split(r"\s*(?:宣布|完成|于|获|融资)", company)[0].strip(" ，,、：:")
        events.append({
            "company": company or None,
            "industry": industry_m.group(1).strip() if industry_m else None,
            "round": round_m.group(1),
            "amount": amount_m.group(1).strip() if amount_m else None,
            "investors": investor_m.group(1).strip() if investor_m else None,
            "date": re.sub(r"\s+", "", date_m.group(1)) if date_m else None,
            "source": None,
        })
    return {"events": events, "_mode": "offline"}


def run_industry(text: str, offline: bool = False) -> dict:
    if offline or not llm.has_api_key():
        return industry_offline(text)
    data = llm.chat_json(INDUSTRY_PROMPT.format(text=text))
    events = data.get("events", data if isinstance(data, list) else [])
    for e in events:
        for f in EVENT_FIELDS:
            e.setdefault(f, None)
    return {"events": events, "_mode": "llm"}


# ---------------------------------------------------------------- 任务 2：文档摘要

DIGEST_PROMPT = """你是投资机构的分析助手。请阅读下面的材料，输出 JSON：

{{"summary": "一段话概括（不超过 120 字）",
  "points": ["关键要点，3-6 条"],
  "metrics": ["材料中出现的具体数字/指标，原文照抄，没有就给空数组"],
  "risks": ["风险或不确定性，没有就给空数组"],
  "open_questions": ["材料没回答、但做决策必须知道的问题，2-4 条"]}}

规则：只输出 JSON；不要编造材料里没有的数字；metrics 必须原文照抄，不要换算。

材料：
{text}"""

METRIC_RE = re.compile(r"[^。；;\n]*?\d[\d.,]*\s*(?:%|亿|万|元|美元|家|个|people|bps|倍)[^。；;\n]*")
RISK_WORDS = ("风险", "不确定", "下滑", "下降", "亏损", "承压", "波动", "挑战", "流失")


def digest_offline(text: str) -> dict:
    sents = [s.strip() for s in re.split(r"(?<=[。；;!?！？\n])", text) if s.strip()]
    metrics = [s.strip("，, ") for s in METRIC_RE.findall(text)][:8]
    risks = [s for s in sents if any(w in s for w in RISK_WORDS)][:5]
    points = sents[:6]
    return {
        "summary": (sents[0][:120] if sents else ""),
        "points": points,
        "metrics": metrics,
        "risks": risks,
        "open_questions": [],
        "_mode": "offline",
    }


def run_digest(text: str, offline: bool = False) -> dict:
    if offline or not llm.has_api_key():
        return digest_offline(text)
    data = llm.chat_json(DIGEST_PROMPT.format(text=text))
    for k in ("points", "metrics", "risks", "open_questions"):
        data.setdefault(k, [])
    data.setdefault("summary", "")
    data["_mode"] = "llm"
    return data


# ---------------------------------------------------------------- 任务 3：会议纪要

MINUTES_PROMPT = """你是投资机构的会议记录助手。请把下面的会议转写整理成结构化纪要，输出 JSON：

{{"topics": ["讨论到的议题"],
  "decisions": ["已明确做出的决定"],
  "actions": [{{"task": "待办事项", "owner": "负责人（没提到就填 null）", "due": "时间（没提到就填 null）"}}],
  "risks": ["会上提到的风险或顾虑"]}}

规则：只输出 JSON；**不要补充会上没说过的内容**；负责人和时间没提到就填 null，不要猜。

会议转写：
{text}"""

DECISION_WORDS = ("决定", "确定", "结论", "定了", "拍板", "通过")
ACTION_WORDS = ("需要", "负责", "跟进", "下周", "本周", "之前", "尽快", "安排", "对接", "整理")
OWNER_RE = re.compile(r"([\u4e00-\u9fa5]{2,3})(?:来|去|负责|跟进|整理|对接)")
DUE_RE = re.compile(r"(下周[一二三四五六日天]?|本周[一二三四五六日天]?|这个月|月底|周[一二三四五六日天]|明天|后天|\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d+\s*个工作日)")


def minutes_offline(text: str) -> dict:
    sents = [s.strip() for s in re.split(r"[。；;\n]", text) if s.strip()]
    topics, decisions, actions, risks = [], [], [], []
    for s in sents:
        if any(w in s for w in DECISION_WORDS):
            decisions.append(s)
        if any(w in s for w in ACTION_WORDS):
            owner_m = OWNER_RE.search(s)
            due_m = DUE_RE.search(s)
            actions.append({
                "task": s,
                "owner": owner_m.group(1) if owner_m else None,
                "due": re.sub(r"\s+", "", due_m.group(1)) if due_m else None,
            })
        if any(w in s for w in RISK_WORDS):
            risks.append(s)
    topics = sents[:3]
    return {"topics": topics, "decisions": decisions[:8], "actions": actions[:10],
            "risks": risks[:5], "_mode": "offline"}


def run_minutes(text: str, offline: bool = False) -> dict:
    if offline or not llm.has_api_key():
        return minutes_offline(text)
    data = llm.chat_json(MINUTES_PROMPT.format(text=text))
    for k in ("topics", "decisions", "actions", "risks"):
        data.setdefault(k, [])
    data["_mode"] = "llm"
    return data


TASKS = {
    "industry": run_industry,
    "digest": run_digest,
    "minutes": run_minutes,
}
