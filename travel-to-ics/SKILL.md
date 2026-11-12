---
name: travel-to-ics
description: 将已规划的旅行行程导出为可导入 Apple 日历、Outlook 或 Google 日历的 .ics 文件。适用于“把行程加到日历”“生成旅行 ICS”“把 QQ 邮箱收到的行程导入 iPhone”等请求；不用于重新规划旅行、代订或生成苹果提醒事项待办。
---

# 旅行行程导出日历

1. 使用用户最后确认的行程，保留绝对日期、当地时间、地点和必要备注。跨年写明年份；跨时区的航班分别使用起飞和抵达机场的当地时间及偏移。只有日期的活动可用全天事件。影响结果的日期、时间或时区歧义先确认；估计时间、待出票场次标为暂定，在备注说明。不要编造航班号、营业时间或预约结果。
2. 整理成 UTF-8 JSON，运行 [scripts/build_ics.py](scripts/build_ics.py)，需要 Python 3.10+，无第三方依赖。提醒用提前分钟数；用户未指定时，只为赴机场、演出等时间敏感事项安排少量提醒。

       {
         "calendar": "跨年旅行",
         "trip_id": "new-year-2027",
         "events": [
           {"id":"airport","title":"出发去机场","start":"2027-01-02T08:45:00+08:00","location":"酒店大堂","alarm_minutes":[30]},
           {"id":"hotel","title":"酒店住宿","start":"2026-12-31","end":"2027-01-02"}
         ]
       }

   calendar、trip_id、events 必填；每项必填 id、title、start。有时刻的输入必须带 UTC 偏移或 Z，输出为 UTC；全天日期的 end 不含当天。结束时间未知可省略，不猜时长。可选 tentative: true、location、notes、alarm_minutes。重导同一行程时保留原 trip_id 和各项 id。

       python scripts/build_ics.py itinerary.json travel.ics

   如果 `trip-planner` 交接了已确认的文件和 SHA-256，直接用原文件并加 `--expect-sha256 <已确认指纹>`。校验失败时不要重算指纹或改用无指纹命令绕过；回到总规划，展示当前版本并重新确认。单独导出用户已确认的现成行程时，仍可使用上面的命令。

3. 交付可下载的 .ics，报告日程数量、提醒数量、时区和关键时刻。核对至少一个航班或预约时间；跨年核对年份。按用户设备和收件方式提供 [导入说明](references/import.md)。只有实际验证后才说手机已导入。
