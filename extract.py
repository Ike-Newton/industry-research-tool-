"""从文本里抽取结构化融资事件。

- 有 LLM_API_KEY 时：调用大模型（OpenAI 兼容接口）抽取
- 没有 key 或 --offline 时：走规则模式，只用来验证流程能跑通
"""
import json
import os
import re
import urllib.request

FIELDS = ["company", "industry", "round", "amount", "investors", "date", "source"]

PROMPT = """你是一个投研数据整理助手。请从下面文本中抽取所有融资事件，输出 JSON 数组。

每个元素包含这些字段：
- company: 公司名
- industry: 所属行业
- round: 融资轮次（如 天使轮 / A轮 / B轮）
- amount: 金额，保留原文（如"数千万人民币""近亿元""未披露"），不要换算
- investors: 投资方数组
- date: 披露日期
- source: 来源（链接或媒体名）

规则：
1. 只输出 JSON，不要任何解释文字。
2. 缺失的字段填 null。
3. 文本里有多条事件就输出多条。
4. 金额一律保留原文，不要做单位换算。

文本：
{text}
"""


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text


def extract_with_llm(text: str) -> list:
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    if not key:
        raise RuntimeError("未设置 LLM_API_KEY，改用 --offline 或先导出 key")

    data = _post_json(
        base + "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT.format(text=text)}],
            "temperature": 0,
        },
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )
    content = data["choices"][0]["message"]["content"]
    return json.loads(_strip_fence(content))


ROUND_RE = re.compile(r"(天使轮|种子轮|Pre-?A\+?轮|A\+?轮|B\+?轮|C\+?轮|D\+?轮|战略融资|并购)")
AMOUNT_RE = re.compile(
    r"((?:近|超|约|逾)?\s*(?:[\d.]+\s*[亿万千万百万]+|数[亿万千万百万]+|"
    r"[一二三四五六七八九十]+[亿万千万百万]+|[亿万千万百万]+)\s*(?:元|美元|人民币)?|未披露)"
)
DATE_RE = re.compile(r"(20\d{2}\s*[-/年]\s*\d{1,2}(?:\s*[-/月]\s*\d{1,2}\s*日?)?)")
INDUSTRY_RE = re.compile(r"[（(]([^）)]{2,12})[）)]")
INVESTOR_RE = re.compile(r"(?:投资方|由|领投方|跟投方)(?:为|是)?\s*([^，,。；;]{2,40})")


def extract_offline(text: str) -> list:
    """规则模式：只解析规整句子，用来验证流程能否跑通。

    抽取质量明显低于模型模式，仅用于演示与冒烟测试。
    """
    rows = []
    for line in re.split(r"[。\n]", text):
        line = line.strip()
        if not line or line.startswith("注意"):
            continue
        round_m = ROUND_RE.search(line)
        if not round_m:
            continue

        amount_m = AMOUNT_RE.search(line)
        date_m = DATE_RE.search(line)
        industry_m = INDUSTRY_RE.search(line)
        investor_m = INVESTOR_RE.search(line)

        company = re.split(r"[（(]", line)[0]
        company = re.split(r"\s*(?:宣布|完成|于|获|融资)\s*", company)[0]
        company = company.strip(" ，,、：:")

        rows.append({
            "company": company or None,
            "industry": industry_m.group(1).strip() if industry_m else None,
            "round": round_m.group(1),
            "amount": amount_m.group(1).strip() if amount_m else None,
            "investors": investor_m.group(1).strip() if investor_m else None,
            "date": re.sub(r"\s+", "", date_m.group(1)) if date_m else None,
            "source": None,
        })
    return rows


def extract(text: str, offline: bool = False) -> list:
    if offline or not os.environ.get("LLM_API_KEY", "").strip():
        return extract_offline(text)
    return extract_with_llm(text)
