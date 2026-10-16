"""Fresh trusted server context for every model request."""
from datetime import datetime, timedelta, timezone

CHINA_TIME = timezone(timedelta(hours=8), name="Asia/Shanghai")


def with_live_context(messages, model, now=None):
    instant = (now or datetime.now(timezone.utc)).astimezone(CHINA_TIME)
    weekday = "一二三四五六日"[instant.weekday()]
    context = ("\n\n【本轮服务器实时信息，优先于历史对话中的时间说法】\n"
               f"北京时间（Asia/Shanghai，UTC+8）：{instant:%Y年%m月%d日 %H:%M:%S}，星期{weekday}。\n"
               f"当前实际调用的模型标识：{model}。\n"
               "用户询问今天日期、星期、现在几点时，直接依据以上服务器时间回答，不要说无法获取当前时间。"
               "只有当前日期和时间由服务器实时提供；尚未配置网页搜索工具。"
               "天气、新闻等实时内容未经查询时应说明无法核实，不要编造或声称已经搜索。")
    result = [dict(message) for message in messages]
    for message in result:
        if message.get("role") == "system":
            message["content"] = (message.get("content") or "") + context
            break
    else:
        result.insert(0, {"role": "system", "content": context})
    return result
