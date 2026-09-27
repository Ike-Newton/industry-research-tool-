"""飞书群自定义机器人：把一段文本发到群里。

用法：
1. 飞书里建一个群 → 群设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 复制 webhook 地址，导出到环境变量：
   PowerShell:  $env:FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
3. python main.py "智能驾驶" --feishu
"""
import json
import os
import urllib.request


def send_text(text: str, webhook: str = "") -> dict:
    url = webhook or os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not url:
        raise RuntimeError("未设置 FEISHU_WEBHOOK")

    payload = {"msg_type": "text", "content": {"text": text}}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))
