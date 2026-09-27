"""飞书群自定义机器人：把结果发到群里。

为什么这里值得单独一个模块：
投研同事不会去跑命令行，他们只会在群里说话。所以"结果能不能进群"
决定了工具是否真的被用起来——这一步比模型本身更影响落地。

配置见 docs/feishu_setup.md（3 步）。
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 20


class FeishuError(RuntimeError):
    pass


def _webhook(url: str = "") -> str:
    url = url or os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not url:
        raise FeishuError("未设置 FEISHU_WEBHOOK（见 docs/feishu_setup.md）")
    return url


def _post(payload: dict, url: str = "") -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _webhook(url), data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise FeishuError("飞书返回 HTTP %s：%s" % (e.code, e.read().decode("utf-8", "ignore")[:200]))


def send_text(text: str, url: str = "") -> dict:
    """发纯文本（最快的一条路，先跑通这个）。"""
    return _post({"msg_type": "text", "content": {"text": text}}, url)


def send_card(title: str, lines: list, url: str = "") -> dict:
    """发交互卡片：更像"工具"，而不是把一大坨文本砸进群里。"""
    content = "\n".join(lines)
    return _post({
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
        },
    }, url)
