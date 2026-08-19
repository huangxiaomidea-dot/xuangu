"""
明日重要事项预测 —— 调用智谱GLM API（自带联网搜索）梳理当前信息面，
生成对A股影响最大的10条大概率事件，仅供参考，不构成投资建议

分两步调用，避免模型用训练时学到的"经验规律"（比如"统计局一般每月中旬发布上月数据"）
覆盖掉搜索结果，把已经发生过的事情误判成"明天才会发生"：
  第一步：先搜索"过去7天内实际已发布"的重要数据/政策，形成一份"已发生事件"清单
  第二步：生成预测时明确要求排除清单里的内容，只能预测确实还没发生的事
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta

_ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_MODEL = "glm-4-plus"

_RECENT_EVENTS_PROMPT = """今天是{today}（{weekday}）。请联网搜索，列出**过去7天内（{week_ago}至{today}）**
中国官方机构（国家统计局、央行、证监会、发改委、财政部、海关总署等）实际已经正式发布的重要经济数据、
政策文件或重大公告，每条注明具体发布日期。这是为了核实"哪些事已经发生过了"，不是预测。

请直接列出条目，每行一条，格式："YYYY-MM-DD：内容摘要"，没有确切把握的不要列。"""

_PROMPT_TEMPLATE = """你是一名专注于A股市场的资深财经分析师。今天是{today}（{weekday}）。

以下是经核实、过去7天内**已经真实发生**的重要事件清单（这些事绝对不能再出现在你的预测里，
因为它们已经发生过了，不是"明天"才会发生的事）：
---
{recent_events}
---

请基于当前最新的公开信息面（宏观经济数据发布日程、央行/政策动向、重要上市公司财报或公告安排、
行业监管消息、地缘政治局势、海外市场联动等），预测明天（{tomorrow}）大概率会**首次**发生的、
对A股市场影响最大的10条消息或事件。

严格要求：
1. 联网搜索核实，不要凭"经验规律"（比如"通常每月中旬发布"）去猜测发布时间——如果某类数据按你的经验
   "应该"在这几天发布，请务必先搜索确认它是否已经在过去发布过，已发布过的不能再预测为明天的事。
2. 只预测确实还没发生、且有明确依据（如官方日程、财报预约、会议安排）支持大概率在明天发生的事件。
3. 不确定的、纯粹靠猜测拼凑的内容，不要列入。

最后必须且只能用如下JSON数组格式输出结果，不要在JSON前后添加任何其他文字说明：

[
  {{"title": "事件标题（20字以内）", "desc": "简要说明，50字以内", "impact": "利好/利空/中性", "sectors": "涉及板块或行业，10字以内"}},
  ...
]

要求正好10条，按你判断的重要性从高到低排列。"""


def _extract_json_array(text: str):
    """从模型输出中提取JSON数组（可能被```json```包裹或前后有说明文字）"""
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def _call_glm(api_key: str, prompt: str, use_search: bool = True) -> str:
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    if use_search:
        payload["tools"] = [{"type": "web_search", "web_search": {"search_result": True}}]
    resp = requests.post(
        _ZHIPU_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def predict_tomorrow_events() -> dict:
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "msg": "服务器未配置 ZHIPU_API_KEY"}

    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    week_ago = now - timedelta(days=7)
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    try:
        # 第一步：核实过去7天内已发生的事，避免第二步把旧事当新事预测
        recent_prompt = _RECENT_EVENTS_PROMPT.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=weekday_map[now.weekday()],
            week_ago=week_ago.strftime("%Y-%m-%d"),
        )
        recent_events = _call_glm(api_key, recent_prompt, use_search=True).strip()
        if not recent_events:
            recent_events = "（未检索到明确的已发布事件）"

        # 第二步：基于已核实的"已发生清单"生成明日预测，排除重复
        predict_prompt = _PROMPT_TEMPLATE.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=weekday_map[now.weekday()],
            tomorrow=tomorrow.strftime("%Y-%m-%d"),
            recent_events=recent_events,
        )
        text = _call_glm(api_key, predict_prompt, use_search=True)
        events = _extract_json_array(text)
        if not isinstance(events, list):
            raise ValueError("模型未返回数组")
    except Exception as e:
        return {"ok": False, "msg": f"生成失败：{e}"}

    return {
        "ok": True,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "target_date": tomorrow.strftime("%Y-%m-%d"),
        "events": events,
        "recent_events_checked": recent_events,
    }
