# 飞书群机器人配置（3 步）

## 1. 建群并添加机器人

1. 打开飞书，进入（或新建）你要接收结果的群
2. 点群右上角 **设置** → **群机器人** → **添加机器人**
3. 选择 **自定义机器人（Custom Bot）**，起个名字（如"投研小助手"）

## 2. 拿到 Webhook 地址

添加完成后，飞书会给你一个地址，形如：

```
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

> 安全设置建议选"**签名校验**"或"**自定义关键词**"。
> 选关键词的话，至少包含 `投研` 或 `纪要`，否则消息会被拒收。

## 3. 配到环境变量里

```powershell
# 当前 PowerShell 窗口有效
$env:FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
```

然后：

```powershell
python main.py industry --input samples/industry_news.txt --feishu
```

群里就会收到一张卡片。

## 常见问题

| 现象 | 原因 |
|---|---|
| `未设置 FEISHU_WEBHOOK` | 环境变量没设，或换了新的终端窗口 |
| 飞书返回 `code: 19021` | 关键词校验没过，消息文本里没有你设置的关键词 |
| 返回 `code: 9499` | 请求太频繁（飞书对自定义机器人有频率限制） |
| 卡片没样式 | 用的是 `send_text` 而不是 `send_card`；两者都能用，卡片更适合"工具"的感觉 |

## 下一步（还没做）

现在只做了**单向推送**（本地 → 群）。要做到 JD 里说的"**一句话就能完成**"，
还需要**接收**群消息：那要用飞书**自建应用**（不是自定义机器人）+ 事件订阅
+ 内网穿透或云函数。这部分是路线图里的下一步。
