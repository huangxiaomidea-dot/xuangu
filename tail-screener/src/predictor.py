"""
明日重要事项预测 —— 调用智谱GLM API（自带联网搜索）梳理当前信息面，
生成对A股影响最大的10条大概率事件，仅供参考，不构成投资建议

准确度依赖两层机制：
1. 固定发布规律锚点（_RELEASE_CALENDAR）—— 中国宏观数据的发布节奏相对固定
   （如LPR每月20日、CPI/PPI次月9-10日、规上工业增加值/社零总额次月15-18日左右），
   把这份规律连同当前真实日期一起喂给模型，让它做"日期算术"判断某类数据这个月
   的发布窗口是否已经过去，而不是完全依赖搜索引擎去猜"这条数据发布了没有"
   （搜索质量对这种核对性问题往往不够可靠，曾出现已发布的数据被误判为"明天的事"）
2. 联网搜索兜底核实过去7天真实发生的具体事件，覆盖日历规律之外的临时性消息
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta

_ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_MODEL = "glm-4-plus"

_RELEASE_CALENDAR = """常见中国宏观数据发布规律（近似窗口，具体以官方公告为准，遇节假日可能顺延）：
- CPI/PPI：次月9-10日左右，国家统计局
- PMI（制造业/非制造业）：当月最后一天或次月1日，国家统计局；财新PMI稍晚1-2天
- 进出口（贸易）数据：次月7-8日左右，海关总署
- 规模以上工业增加值、社会消费品零售总额、固定资产投资：次月15-18日左右，国家统计局
  （通常与GDP季度数据一起发布，1、4、7、10月中旬这几项数据同时公布上季度/上月情况）
- GDP季度数据：季度结束后next月15-18日左右，国家统计局
- LPR（贷款市场报价利率）：每月20日，全国银行间同业拆借中心
- M2/社融/新增贷款数据：次月9-15日左右，中国人民银行
- 外汇储备：每月7日左右，国家外汇管理局
- 美国CPI：次月10-15日左右；美联储议息会议纪要：会议后约3周；美国非农就业：次月第一个周五"""

_RECENT_EVENTS_PROMPT = """今天是{today}（{weekday}）。请联网搜索，列出**过去10天内（{week_ago}至{today}）**
中国官方机构（国家统计局、央行、证监会、发改委、财政部、海关总署等）实际已经正式发布的重要经济数据、
政策文件或重大公告，每条注明具体发布日期。这是为了核实"哪些事已经发生过了"，不是预测。

请直接列出条目，每行一条，格式："YYYY-MM-DD：内容摘要"，没有确切把握的不要列。"""

_PROMPT_TEMPLATE = """你是一名专注于A股市场的资深财经分析师。今天是{today}（{weekday}）。

【参考锚点1：常见发布规律】
{release_calendar}

请先用今天的真实日期（{today}）和上面这份发布规律做"日期算术"：任何一类数据，如果它这个月/本周期
对应的发布窗口已经落在今天或今天之前，就说明大概率已经发布过了，绝对不能再把它列为"明天"的预测事件；
只有当"明天"（{tomorrow}）恰好落在某类数据的发布窗口内，才可以谨慎列入，并在desc里注明这是基于常规
发布节奏的推测。

【参考锚点2：联网核实过去10天真实发生的事】（用于捕捉规律之外的临时性消息，同时可交叉验证锚点1的判断）
---
{recent_events}
---
以上清单里的事已经发生过了，绝对不能再出现在你的预测里。

请基于以上两份参考信息，预测明天（{tomorrow}）大概率会**首次**发生的、对A股市场影响最大的10条消息或事件
（宏观数据发布、央行/政策动向、重要上市公司财报或公告安排、行业监管消息、地缘政治局势、海外市场联动等）。

严格要求：
1. 先做日期算术排除掉本轮已经发布过的数据，再看是否有新的信息补充；不确定的、纯粹靠猜测拼凑的内容不要列入。
2. 只预测确实还没发生、且有明确依据（发布规律、官方日程、财报预约、会议安排）支持大概率在明天发生的事件。

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
    week_ago = now - timedelta(days=10)
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    try:
        # 第一步：核实过去10天内已发生的事，作为日期规律锚点之外的补充/交叉验证
        recent_prompt = _RECENT_EVENTS_PROMPT.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=weekday_map[now.weekday()],
            week_ago=week_ago.strftime("%Y-%m-%d"),
        )
        recent_events = _call_glm(api_key, recent_prompt, use_search=True).strip()
        if not recent_events:
            recent_events = "（未检索到明确的已发布事件）"

        # 第二步：用"固定发布规律锚点 + 已核实清单"双重约束生成明日预测
        predict_prompt = _PROMPT_TEMPLATE.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=weekday_map[now.weekday()],
            tomorrow=tomorrow.strftime("%Y-%m-%d"),
            release_calendar=_RELEASE_CALENDAR,
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
