"""大模型调用层：OpenAI 兼容接口 + JSON 容错 + 重试。

设计取舍：
- 不引第三方依赖（只用标准库），保证"拿到就能跑"。
- 所有模型输出都当**不可信输入**处理：剥代码围栏、定位 JSON、解析失败重试一次。
- 没有配置 key 时，调用方应显式走 offline 分支，而不是在这里静默降级。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class LLMError(RuntimeError):
    pass


def has_api_key() -> bool:
    return bool(os.environ.get("LLM_API_KEY", "").strip())


def _endpoint() -> str:
    return os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"


def _model() -> str:
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL)


def chat(prompt: str, system: str = "", temperature: float = 0.0,
         retries: int = 2, timeout: int = 90) -> str:
    """调一次模型，返回纯文本。失败按指数退避重试。"""
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        raise LLMError("未设置 LLM_API_KEY（可加 --offline 走规则模式）")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": _model(),
        "messages": messages,
        "temperature": temperature,
    }).encode("utf-8")

    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            _endpoint(),
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            last_err = LLMError("HTTP %s: %s" % (e.code, body))
        except Exception as e:  # 网络抖动、超时、返回结构异常
            last_err = LLMError("%s: %s" % (type(e).__name__, e))
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _first_json_block(text: str):
    """从文本里挖出第一个完整的 JSON 对象或数组（模型偶尔会加解释）。"""
    text = _strip_fence(text)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("未找到可解析的 JSON")


def chat_json(prompt: str, system: str = "", retries: int = 2):
    """让模型返回 JSON，并做容错解析；解析失败时追加一句修复提示重试。"""
    last_err = None
    current = prompt
    for _ in range(retries + 1):
        raw = chat(current, system=system, retries=1)
        try:
            return _first_json_block(raw)
        except Exception as e:
            last_err = e
            current = prompt + "\n\n注意：上一次输出不是合法 JSON（%s）。请**只输出 JSON**，不要任何解释、不要 Markdown 代码围栏。" % e
    raise LLMError("模型连续返回无法解析的 JSON：%s" % last_err)
