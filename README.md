# Travel Skills · 旅行规划技能集

一套面向 Codex 和 OpenCode 的旅行技能：按预算找国内机票、按日期选酒店、排每日行程，再把确认后的计划导出为可导入日历的 `.ics` 文件。四个技能可以单独使用，也可以由 `trip-planner` 串起来。

## 快速开始

> 用 trip-planner 帮我规划一次旅行：2026 年 12 月 30 日从无锡出发，2027 年 1 月 2 日返回。东北城市都可以，机票单程含税不超过 ¥800，酒店每间每晚 ¥500–800。先给我看完整行程，确认后再生成苹果日历文件。

收到方案后，可以回复「把返程改成中午，早市挪到前一天」继续调整。满意后回复 **「按这版生成日历」**。初次要求生成日历，不等于确认还没看到的行程；改过的版本会重新展示，等确认后才导出。

## 技能列表

| 技能 | 适合用来做什么 | 示例 |
| --- | --- | --- |
| [trip-planner](trip-planner/SKILL.md) | 组合机票、住宿和景点，按起降时间、换酒店和预约要求排逐日行程 | 「行程已订，帮我按 1 月 2 日中午的航班调整游玩顺序」 |
| [flight-lowprice](flight-lowprice/SKILL.md) | 按区域、日期和含税预算筛国内航线，比较往返组合 | 「无锡出发，东北有哪些单程含税 ¥800 以内的目的地？」 |
| [hotel-pick](hotel-pick/SKILL.md) | 按具体入住日期、位置、价格、权益和退改比较酒店及房券 | 「沈阳中街住一晚，¥500–800，舒适优先」 |
| [travel-to-ics](travel-to-ics/SKILL.md) | 把已确认的行程导出为 Apple 日历、Outlook 或 Google 日历可用的 `.ics`，支持时区、全天日程和提前提醒 | 「把这份确认过的行程导出为 .ics，去机场提前 30 分钟提醒」 |

## 安装

克隆仓库，或从 GitHub 下载 ZIP 后解压：

```sh
git clone https://github.com/xxx123123/travel-skills.git
```

把需要的**整个技能目录**复制到以下位置之一，保留其中的 `SKILL.md`、脚本和引用文件。使用完整流程时，将四个目录并排放在同一个技能目录下。

| 使用范围 | 技能目录 |
| --- | --- |
| Codex 和 OpenCode，当前项目 | 项目根目录下的 `.agents/skills/` |
| Codex 和 OpenCode，当前用户 | `~/.agents/skills/`（Windows 对应用户主目录下的 `.agents\skills\`） |

例如，项目安装后应有 `.agents/skills/trip-planner/SKILL.md`。开启新会话后，Codex 可以用 `$trip-planner` 指定技能；在 OpenCode 中可以直接写「使用 trip-planner」。脚本需要 **Python 3.10 或更新版本**，无需安装第三方 Python 库；查机票、酒店和景点信息需要联网。

安装参考：[Codex](https://developers.openai.com/api/reference/cli) · [OpenCode](https://docs.opencode.ai/docs/skills/)

## 直接运行脚本

在仓库根目录运行。机票示例中的日期可替换为你的出行日期：

```sh
python flight-lowprice/scripts/lowprice.py --from WUX --dates 2026-12-30 --region 东北 --max-price 800 --group-by-region --json
python travel-to-ics/scripts/build_ics.py itinerary.json travel.ics
```

`--max-price 800` 含 ¥800；严格低于 ¥800 用 `--under-price 800`。日历输入 JSON 示例见 [travel-to-ics](travel-to-ics/SKILL.md)。

## 导入日历

下载生成的 `.ics` 后，按设备选择导入方式。如果附件来自 QQ 邮箱，先存到 iPhone 的「文件」。没有「添加日程」入口时，可用支持批量导入的 App，或在电脑导入 Outlook、Google 日历，再同步到手机。Mac 用户也可以直接导入 iCloud 日历。详见 [导入与排查指南](travel-to-ics/references/import.md)。

## 价格与预订

- 机票日历价用于筛选，具体机场、班次、税费、行李和退改以购票页为准。
- 酒店房券要核对目标日期的库存、加价及退款规则；显示促销价不代表那一晚有房。
- 技能提供规划、比价和导出，不代下单。`.ics` 需要用户自行导入，导入后建议核对一个关键时刻和提醒。
