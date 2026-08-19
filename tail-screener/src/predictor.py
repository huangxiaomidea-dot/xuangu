"""
明日重要事项预测 —— 调用智谱GLM API（自带联网搜索）梳理当前信息面，
生成对A股影响最大的10条大概率事件，仅供参考，不构成投资建议
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta

_ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_MODEL = "glm-4-plus"

_PROMPT_TEMPLATE = """你是一名专注于A股市场的资深财经分析师。今天是{today}（{weekday}）。

请基于当前最新的公开信息面（宏观经济数据发布日程、央行/政策动向、重要上市公司财报或公告安排、
行业监管消息、地缘政治局势、海外市场联动等），预测明天（{tomorrow}）大概率会发生的、
对A股市场影响最大的10条消息或事件。

请优先使用联网搜索核实近期真实动态，不要凭空编造具体数字或已发生的确定性事实之外的细节。

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


def predict_tomorrow_events() -> dict:
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "msg": "服务器未配置 ZHIPU_API_KEY"}

    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    prompt = _PROMPT_TEMPLATE.format(
        today=now.strftime("%Y-%m-%d"),
        weekday=weekday_map[now.weekday()],
        tomorrow=tomorrow.strftime("%Y-%m-%d"),
    )

    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search", "web_search": {"search_result": True}}],
        "temperature": 0.4,
    }

    try:
        resp = requests.post(
            _ZHIPU_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
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
    }
