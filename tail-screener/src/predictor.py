"""
明日相关事件预测 —— 针对今日选出的TOP3个股，各预测3条明日大概率发生、
可能影响该股走势的公司相关消息（调用智谱GLM API，自带联网搜索），仅供参考，不构成投资建议
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta

_ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_MODEL = "glm-4-plus"

_PROMPT_TEMPLATE = """你是一名专注于A股上市公司跟踪的资深研究员。今天是{today}（{weekday}）。

以下是今日选出的3只关注个股：
{company_list}

请针对**每一只**个股，联网搜索该公司最新的公开信息（近期公告、财报预约、股东大会/解禁安排、
行业事件、监管动态、机构评级、媒体报道等），预测明天（{tomorrow}）大概率会发生、
可能影响该股走势的3条具体事件或消息。

严格要求：
1. 必须联网搜索核实，不要凭空编造具体数字或未经核实的传闻。
2. 只预测确实还没发生、且有明确依据（公告预约、监管日程、行业惯例等）支持大概率在明天发生的事，
   如果搜索不到某公司足够具体的信息，可以给出基于行业/板块层面的合理判断，并在desc中说明这是推测。
3. 不要把已经发生过的旧闻当成"明天"的事。

最后必须且只能用如下JSON数组格式输出结果（每只股票一个对象，events数组正好3条），
不要在JSON前后添加任何其他文字说明：

[
  {{"code": "股票代码", "name": "公司名称", "events": [
    {{"title": "事件标题（20字以内）", "desc": "简要说明，50字以内", "impact": "利好/利空/中性"}},
    ...共3条
  ]}},
  ...共{count}只股票
]"""


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


def _call_glm(api_key: str, prompt: str) -> str:
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search", "web_search": {"search_result": True}}],
        "temperature": 0.3,
    }
    resp = requests.post(
        _ZHIPU_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def predict_company_events(companies: list) -> dict:
    """
    companies: [{"code": "600xxx", "name": "公司名"}, ...]（今日TOP3）
    返回每只股票3条明日相关事件预测
    """
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "msg": "服务器未配置 ZHIPU_API_KEY"}
    if not companies:
        return {"ok": False, "msg": "暂无今日选股数据，无法预测相关事件"}

    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    company_list = "\n".join(f"- {c['name']}（{c['code']}）" for c in companies)

    prompt = _PROMPT_TEMPLATE.format(
        today=now.strftime("%Y-%m-%d"),
        weekday=weekday_map[now.weekday()],
        tomorrow=tomorrow.strftime("%Y-%m-%d"),
        company_list=company_list,
        count=len(companies),
    )

    try:
        text = _call_glm(api_key, prompt)
        results = _extract_json_array(text)
        if not isinstance(results, list):
            raise ValueError("模型未返回数组")
    except Exception as e:
        return {"ok": False, "msg": f"生成失败：{e}"}

    return {
        "ok": True,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "target_date": tomorrow.strftime("%Y-%m-%d"),
        "companies": results,
    }
