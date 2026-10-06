"""翻译表：所有界面文字（页面、页面里的脚本、规则报错、MCP 工具说明、命令行输出）都从这里取。

一张表，每条两种语言并排写：`键: (中文, English)`——缺哪一种一眼看得出，测试也会逐条核对占位符一致。
配置里 `lang: "zh" | "en"` 决定用哪一列；`<html lang>` 跟着变。

    from team_board.i18n import t
    t("err.missing", key="title")        # 当前语言
    tr("en", "err.missing", key="title") # 指定语言

只用标准库；不依赖配置模块（配置模块反过来用它报错）。
"""
from __future__ import annotations

import contextvars

LANGS = ("zh", "en")
_IDX = {"zh": 0, "en": 1}
_HTML_LANG = {"zh": "zh-CN", "en": "en"}

M: dict[str, tuple[str, str]] = {
    # ---------------------------------------------------------------- 通用小件
    "app.title": ("团队看板", "Team Board"),
    "sep": ("、", ", "),
    "paren": ("（{text}）", " ({text})"),
    "range": ("{start} 至 {end}", "{start} – {end}"),
    "tz.note": ("（{label}）", " ({label})"),
    "yes": ("是", "Yes"),
    "no": ("否", "No"),
    "none": ("没有", "None"),
    "none_full": ("没有。", "None."),
    "weekdays": ("一,二,三,四,五,六,日", "Mon,Tue,Wed,Thu,Fri,Sat,Sun"),
    "months": ("1 月,2 月,3 月,4 月,5 月,6 月,7 月,8 月,9 月,10 月,11 月,12 月", "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec"),
    "unit.hour": ("{n} 小时", "{n} hour"),
    "unit.hours": ("{n} 小时", "{n} hours"),
    "unit.day": ("{n} 天", "{n} day"),
    "unit.days": ("{n} 天", "{n} days"),
    "dur.under_minute": ("不到 1 分钟", "under 1 min"),
    "dur.minutes": ("{n} 分钟", "{n} min"),
    "person.unassigned": ("未指派", "unassigned"),
    "role.owner": ("团队负责人", "Team owner"),
    "role.member": ("成员", "Member"),
    "via.ai": ("（经 AI）", " (via AI)"),
    "via.seed": ("（示例数据）", " (demo data)"),
    "status.approved": ("进行中", "In progress"),
    "status.active": ("进行中", "In progress"),
    "status.done": ("已完成", "Done"),
    "status.abandoned": ("已放弃", "Abandoned"),
    "pause.dependency": ("等依赖", "Waiting on a dependency"),
    "pause.external": ("等外部", "Waiting on someone outside"),
    "zoom.day": ("一天", "1 day"),
    "zoom.week": ("一周", "1 week"),
    "zoom.2week": ("两周", "2 weeks"),
    "zoom.month": ("一个月", "1 month"),
    "zoom.quarter": ("一季度", "1 quarter"),
    "due.long_term": ("长期", "Ongoing"),
    "due.unset": ("未定", "Not set"),
    "when.now": ("现在", ""),
    "when.then": ("{time}{tz}那时", " as of {time}{tz}"),
    "when.then_short": ("那时", " at that point"),
    "goal.ref": ("{gnum}「{title}」", "{gnum} “{title}”"),
    "sample.prefix": ("示例·", "Sample · "),
    "sample.tag": ("示例", "Sample"),
    "link.kind.link": ("普通关联", "Plain link"),
    "link.kind.subcontract": ("分包", "Subcontract"),

    # ---------------------------------------------------------------- 配置报错
    "cfg.missing": ("找不到配置文件 {path}。先运行：python3 -m team_board init",
                    "Config file not found: {path}. Run first: python3 -m team_board init"),
    "cfg.not_json": ("配置文件 {path} 不是合法的 JSON：{error}", "Config file {path} is not valid JSON: {error}"),
    "cfg.not_object": ("配置的最外层必须是一个对象", "The config must be a JSON object"),
    "cfg.lang": ("lang 只能是 zh 或 en，收到 {lang}", "lang must be zh or en, got {lang}"),
    "cfg.auth": ("auth 只能是 local 或 token，收到 {auth}", "auth must be local or token, got {auth}"),
    "cfg.port": ("port 必须是整数，收到 {port}", "port must be an integer, got {port}"),
    "cfg.zone_shape": ("{key} 要写成时区名，或 {{\"name\": 时区名, \"label\": 页面上的叫法}}",
                       "{key} must be a time-zone name, or {{\"name\": zone, \"label\": display label}}"),
    "cfg.zone_unknown": ("{key} 的时区名认不出：{name}（要写 IANA 名，例如 Europe/Berlin）",
                         "Unknown time zone in {key}: {name} (use an IANA name such as Europe/Berlin)"),
    "cfg.list_empty": ("{key} 不能为空，至少写一项", "{key} must not be empty"),
    "cfg.name_missing": ("{key} 第 {n} 项缺少 name", "{key} item {n} has no name"),
    "cfg.color_bad": ("{key} 的颜色要写成 #rrggbb，收到 {color}", "Color for {key} must look like #rrggbb, got {color}"),
    "cfg.duplicate": ("{key} 里有重复：{value}", "Duplicate in {key}: {value}"),
    "cfg.person_id": ("people 的 id 只能是小写字母开头的字母、数字、-、_，收到 {id}",
                      "A person id must start with a lowercase letter and use only letters, digits, - and _; got {id}"),
    "cfg.letter": ("{id} 的出生号字母要是一个大写字母（G 留给看板的目标编号），收到 {letter}",
                   "The source letter for {id} must be one uppercase letter (G is reserved for goal numbers), got {letter}"),
    "cfg.role": ("{id} 的 role 只能是 owner 或 member，收到 {role}", "role for {id} must be owner or member, got {role}"),
    "cfg.no_owner": ("people 里至少要有一个 role 为 owner 的人", "At least one person must have the role owner"),
    "cfg.token_missing": ("令牌模式（auth: token）下每个人都要有 token", "In token mode (auth: token) every person needs a token"),
    "cfg.unsafe_bind": ("本地试用模式（auth: local，免登录）只能监听本机回环地址（127.0.0.1）。要给别的机器访问，"
                        "把 auth 改成 token，或把 host 改回 127.0.0.1 并在前面放反向代理。当前 host：{host}",
                        "Local mode (auth: local, no login) may only listen on loopback (127.0.0.1). To serve other machines, "
                        "set auth to token, or keep host at 127.0.0.1 behind a reverse proxy. Current host: {host}"),
    "cfg.github_shape": ("github 一节必须是对象", "The github section must be an object"),
    "cfg.github_no_repo": ("开启 GitHub 同步（github.enabled）至少要写一个仓库", "github.enabled needs at least one repo"),
    "cfg.repo_bad": ("仓库要写成 owner/name，收到 {repo}", "A repo must be written owner/name, got {repo}"),
    "cfg.repo_line": ("仓库 {repo} 归到的线「{line}」不在 lines 里", "Line “{line}” for repo {repo} is not in lines"),
    "cfg.label_pattern": ("github.label_map 每项要有 pattern（正则）和 state，这一项不对：{pattern}",
                          "Each github.label_map item needs a pattern (regex) and a state; bad item: {pattern}"),

    # ---------------------------------------------------------------- 登录
    "auth.bad_token": ("令牌不对", "Invalid token"),
    "auth.api_login": ("没有登录：请求要带 Authorization: Bearer <个人令牌>",
                       "Not signed in: send Authorization: Bearer <your personal token>"),
    "auth.local_only": ("只有本地试用模式才能这样切换身份", "Switching identity is only available in local mode"),
    "login.title": ("登录", "Sign in"),
    "login.help": ("用你的个人令牌登录（找团队负责人要，或看配置文件里你那一行的 token）。",
                   "Sign in with your personal token (ask a team owner, or see your token in the config file)."),
    "login.placeholder": ("个人令牌", "Personal token"),
    "login.submit": ("登录", "Sign in"),

    # ---------------------------------------------------------------- 页壳
    "nav.board": ("看板", "Board"),
    "nav.board_tip": ("团队的目标时间线：目标、负责人、各环节耗时、延期与卡点",
                      "The team's goal timeline: goals, owners, time per stage, delays and blockers"),
    "nav.practice": ("练手看板", "Practice board"),
    "nav.practice_tip": ("数据完全隔离的练手看板：随便操作、一键重置，不碰正式记录",
                         "A fully isolated sandbox: try anything, reset in one click, real records untouched"),
    "ui.whoami_tip": ("我是谁", "Who I am"),
    "ui.switch_person": ("本地试用 · 选「我是谁」", "Local mode · pick who you are"),
    "ui.local_mode_note": ("本地试用模式，不用登录。给团队用时改成令牌模式（配置 auth: token）。",
                           "Local mode, no sign-in. For team use, switch to token mode (auth: token in the config)."),
    "ui.logout": ("退出登录", "Sign out"),

    # ---------------------------------------------------------------- 首页
    "ui.practice_prefix": ("练手 · ", "Practice · "),
    "ui.sample_prefix": ("示例看板 · ", "Sample board · "),
    "ui.practice_board": ("练手看板", "Practice board"),
    "ui.practice_badge": ("练手", "practice"),
    "ui.practice_banner": ("：这里的记录不是真的——内容是上次重置时正式看板的一份副本，随便立项、开环节、改期、口述录入，"
                           "都不碰正式数据，AI 也不会把这里的事推进个人看板。想回到正式数据的样子就重置。",
                           ": nothing here is real. It is a copy of the real board from the last reset, so create goals, start stages, "
                           "move dates and dictate freely. Real data is untouched and the AI won't push anything from here to a personal board. "
                           "Reset to get back to a fresh copy."),
    "ui.practice_reset": ("重置练手数据", "Reset practice data"),
    "ui.back_to_real": ("← 回正式看板", "← Back to the real board"),
    "ui.sample_board": ("示例看板", "Sample board"),
    "ui.sample_banner": ("：真实目标照常显示，另加标了「示例」的假设案例，用来看这个看板设计合不合理。示例不进真实记录、不算谁手上的事。",
                         ": real goals show as usual, plus hypothetical cases tagged “Sample” for judging the board's design. "
                         "Samples are not real records and are nobody's actual work. "),
    "ui.back_to_real_from_sample": ("← 回真实看板", "← Back to the real board"),
    "ui.practice_reset_at": ("练手数据是 {time}{tz}重置的", "Practice data was reset at {time}{tz}"),
    "ui.practice_reset_unknown": ("练手数据是上次重置时复制的", "Practice data was copied at the last reset"),
    "ui.practice_gh_frozen": ("，GitHub 数据停在那一刻、不再更新", "; GitHub data is frozen at that moment"),
    "ui.gh_as_of": ("GitHub 数据截至 {time}{tz}", "GitHub data as of {time}{tz}"),
    "ui.gh_syncing": ("正在同步（{time}{tz} 开始）", "Syncing (started {time}{tz})"),
    "ui.gh_stale": ("已超过 30 分钟没有更新", "Not updated for over 30 minutes"),
    "ui.gh_last_error": ("上次同步失败：{error}", "Last sync failed: {error}"),
    "ui.gh_incomplete": ("有 {n} 张单的状态记录还没取全，每轮同步都会重试",
                         "{n} issue(s) have incomplete status history; every sync retries them"),
    "ui.sync_now": ("立即同步", "Sync now"),
    "ui.i_am": ("我是：{who}", "I am: {who}"),
    "ui.dictation": ("口述录入", "Dictation"),
    "ui.dictation_sub": ("进展、要立项的目标，讲清楚交给 AI 录进看板，不用填表",
                         "Say what happened or what to start; the AI records it on the board. No forms."),
    "ui.blockers": ("卡点", "Blockers"),
    "ui.no_blockers": ("现在没有卡点。", "No blockers right now."),
    "ui.timeline": ("时间线", "Timeline"),
    "ui.everyone": ("所有人", "Everyone"),
    "ui.all_lines": ("所有线", "All lines"),
    "ui.active_only": ("只看进行中", "In progress only"),
    "ui.filter": ("筛选", "Filter"),
    "ui.filtering": ("正在只看", "Showing only"),
    "ui.filtering_person": ("{person}的事", "{person}'s work"),
    "ui.show_all": ("看全部", "Show all"),
    "ui.one_screen": ("一屏看", "One screen ="),
    "ui.prev_screen": ("← 往前一屏", "← Back one screen"),
    "ui.back_to_today": ("回到今天", "Today"),
    "ui.next_screen": ("往后一屏 →", "Forward one screen →"),
    "ui.jump_to": ("跳到", "Jump to"),
    "ui.pick_day": ("选一天", "Pick a day"),
    "ui.pick_week": ("选一周", "Pick a week"),
    "ui.pick_month": ("选一个月", "Pick a month"),
    "ui.pick_quarter": ("选一个季度", "Pick a quarter"),
    "ui.lines_only": ("只看各条线", "Lines only"),
    "ui.expand_all": ("全部展开", "Expand all"),
    "ui.show_ended": ("连已结束的都显示", "Show ended goals too"),
    "ui.see_sample": ("看示例看板（假设数据）", "Sample board (hypothetical data)"),
    "ui.timeline_help": ("时间线是一整条，左右拖动看别的时间段；缩放只改一屏看多长。进行中的事从立项起一直在、往后画虚线（还在做）；"
                         "已完成、已放弃的只在拖到它那段时间时才出现（勾「连已结束的都显示」可关掉，勾上后立项前也列着）。"
                         "计划完成可以精确到小时，缩到「一天」能看到几点；天数是日历时间。",
                         "The timeline is one long strip: drag sideways to see other periods; zoom only changes how much fits on a screen. "
                         "Goals in progress stay visible from the day they were created and continue as a dashed line (still going); "
                         "done and abandoned goals appear only when you drag to their period (tick “Show ended goals too” to always list everything). "
                         "Due dates can be set to the hour; zoom to “1 day” to see the time. Days are calendar days."),
    "ui.doing": ("现在在做什么", "What's happening now"),
    "ui.doing_sub": ("备忘：各条线正在推进的目标、谁负责、到哪个环节；只拆给下层在做的上层不列，点名字看详情",
                     "At a glance: goals moving on each line, who owns them and which stage they're in. "
                     "Parents whose work is all in sub-goals aren't listed. Click a name for details."),
    "ui.doing_now": ("现在：{stage} · 计划 {due}", "Now: {stage} · due {due}"),
    "ui.over_by": ("已超出 {late}", "{late} overdue"),
    "ui.nothing_in_progress": ("没有进行中的事。", "Nothing in progress."),
    "ui.weekly_docs": ("周会文档", "Weekly notes"),
    "ui.week_of": ("{day} 那一周：", "Week of {day}: "),
    "idx.no_line": ("没有这条线：{line}，已显示全部", "No such line: {line}. Showing all."),
    "idx.no_person": ("没有这个人：{person}，已显示全部", "No such person: {person}. Showing everyone."),
    "idx.no_zoom": ("没有这个缩放：{zoom}，已用「{default}」", "No such zoom: {zoom}. Using “{default}”."),
    "idx.nothing_for": ("{person}在这条线上没有事", "Nothing for {person} on this line"),
    "idx.no_goals": ("还没有目标", "No goals yet"),
    "jump.week": ("{day} 那周", "Week of {day}"),
    "jump.day": ("{day} 周{weekday}", "{day} {weekday}"),
    "jump.month": ("{year} 年 {month} 月", "{name} {year}"),
    "jump.quarter": ("{year} 年第 {q} 季度", "Q{q} {year}"),
    "jump.current": ("{label}（{now}）", "{label} ({now})"),
    "jump.this_week": ("本周", "this week"),
    "jump.today": ("今天", "today"),
    "jump.this_month": ("本月", "this month"),
    "jump.this_quarter": ("本季度", "this quarter"),
    "doing.stages_done": ("环节都已结束", "all stages ended"),
    "doing.helping": ("替{owner}做「{stages}」", "doing {stages} for {owner}"),
    "sync.never": ("从未同步", "never synced"),
    "sync.no_token": ("没有 GitHub 凭证：启动服务前设好环境变量 {env}", "No GitHub token: set the {env} environment variable before starting the server"),
    "sync.already_running": ("已经有一轮同步在跑，稍后刷新页面看结果", "A sync is already running; refresh in a moment"),
    "sync.started": ("已开始同步（在后台跑，第一次全量可能要十几分钟），稍后刷新页面看结果",
                     "Sync started in the background (the first full run can take ten minutes or more); refresh in a moment"),
    "msg.practice_reset": ("练手数据已重置为此刻的正式数据", "Practice data reset to a fresh copy of the real board"),
    "msg.saved": ("已保存", "Saved"),

    # ---------------------------------------------------------------- 卡点
    "blk.late": ("延期", "Late"),
    "blk.dragged": ("被拖住", "Held up"),
    "blk.dep": ("依赖冲突", "Dependency at risk"),
    "blk.pause": ("暂停", "Paused"),
    "blk.stale": ("环节可能过期", "Stage may be stale"),
    "blk.subcontract": ("分包等太久", "Subcontract waiting"),
    "blk.version": ("版本", "Version"),
    "blk.late_text": ("{title}：已超出计划 {late}", "{title}: {late} past plan"),
    "blk.late_external": ("（其中等外部 {ext}）", " (of which {ext} waiting on someone outside)"),
    "blk.dragged_text": ("{title}：被「{names}」拖过了预计完成日", "{title}: pushed past its due date by “{names}”"),
    "blk.pause_text": ("{title}：{kind} {dur}", "{title}: {kind}, {dur}"),
    "blk.pause_waiting": ("，等「{title}」", ", waiting for “{title}”"),
    "blk.stale_text": ("{title}：「{stages}」的记录已 {dur}没动，但关联的单最近有动静",
                       "{title}: no stage change on “{stages}” for {dur}, yet linked issues are active"),
    "blk.subcontract_text": ("{title}：分包单 {ref} 已等 {dur}，可考虑改成子目标",
                             "{title}: subcontract issue {ref} has waited {dur}; consider making it a sub-goal"),
    "blk.dep_text": ("{title}：{text}", "{title}: {text}"),
    "blk.version_text": ("版本 {title}：已超出计划 {late}", "Version {title}: {late} past plan"),
    "dep.no_due": ("等的「{title}」还没有预计完成日", "“{title}”, which it waits on, has no due date yet"),
    "dep.late": ("等的「{title}」预计 {due} 完成，晚于需要它的 {need}",
                 "“{title}”, which it waits on, is due {due}, later than the {need} it is needed by"),

    # ---------------------------------------------------------------- 时间线
    "tl.today": ("今天", "Today"),
    "tl.now": ("现在", "now"),
    "tl.running": ("进行中", "in progress"),
    "tl.no_stages": ("没分环节", "No stages"),
    "tl.no_stages_tip": ("没分环节，只看起止：{start} 至 {end}{tz}", "No stages, just start and end: {start} – {end}{tz}"),
    "tl.future_no_stages": ("还在做（没分环节）：从现在起往后", "Still going (no stages): from now on"),
    "tl.stage_tip": ("{stage}（{who}）：{start} 至 {end}{tz}", "{stage} ({who}): {start} – {end}{tz}"),
    "tl.future_stage": ("还在做：{stage}（{who}）进行中", "Still going: {stage} ({who}) in progress"),
    "tl.pause_tip": ("{kind}：{start} 至 {end}{tz}", "{kind}: {start} – {end}{tz}"),
    "tl.plan": ("计划 {due}", "Due {due}"),
    "tl.plan_was": ("（原定 {due}）", " (was {due})"),
    "tl.plan_unset": ("计划未定", "No due date"),
    "tl.replan": ("改到 {due}", "Moved to {due}"),
    "tl.start": ("开始 {day}", "Start {day}"),
    "tl.late": ("延期 {late}", "{late} late"),
    "tl.done_at": ("完成 {time}", "done {time}"),
    "tl.version_tip": ("{title}：{start} 至 {end}{tz}", "{title}: {start} – {end}{tz}"),
    "tl.version_future": ("{title}：还在做", "{title}: still going"),
    "tl.belongs": ("属于 {gnum} {title}", "Part of {gnum} {title}"),
    "tl.elsewhere": ("另 {n} 块在{lines}", "{n} more part(s) on {lines}"),
    "tl.source_tip": ("出生号：个人看板立项时发的号，推上团队看板后也不变",
                      "Source number: issued by a personal board when the goal was created; it never changes after being pushed here"),
    "tl.others_tip": ("负责人以外还涉及：", "Also involved besides the owner: "),
    "tl.version_owners_tip": ("挂在这个版本下的目标的负责人", "Owners of the goals attached to this version"),
    "tl.carried_tip": ("这次发布装着：", "This release carries: "),
    "tl.carries": ("装着 ", "Carries "),
    "tl.life_tip": ("目标从开始到现在（或结束）", "The goal from start to now (or to its end)"),
    "tl.life_future_tip": ("还在做：眼下没有环节开着（等别人 / 暂停），从现在起往后",
                           "Still going: no stage open right now (waiting / paused), from now on"),
    "tl.over_tip": ("超出计划完成日（延期）", "Past the due date (late)"),
    "ver.title": ("版本 {name}", "Version {name}"),
    "ver.unsynced": ("{ref}（还没同步到）", "{ref} (not synced yet)"),
    "jst.out_of_window": ("另有 {n} 项不在这段时间（已结束的，或那时还没立项的）",
                          "{n} more not in this period (ended, or not created yet back then)"),
    "jst.moved_to": ("拖到了 {day} 这段：", "Now at {day}: "),
    "jst.appeared": ("出现 {n} 项属于这段时间的", "{n} item(s) from this period appeared"),
    "jst.comma": ("，", ", "),
    "jst.left": ("{n} 项不属于这段时间的退出", "{n} item(s) outside this period left"),
    "jst.expand": ("展开", "Expand"),
    "jst.collapse": ("折叠", "Collapse"),
    "jst.folded": (" · 已折叠 {n} 项", " · {n} folded"),
    "jst.family_inside": (" · 里面还有同一家的 {n} 块", " · {n} more of this family inside"),

    # ---------------------------------------------------------------- 图例
    "lg.pause": ("暂停（等依赖 / 等外部）", "Paused (waiting on a dependency / on someone outside)"),
    "lg.no_stages": ("灰条「没分环节」= 没有环节记录，只看起止：笼统的事项、按旧方式做的目标，或刚立项还没开始记环节",
                     "Grey bar “No stages” = no stage records, just start and end: a broad goal, or one that hasn't started tracking stages"),
    "lg.marks": ("「开始 09-28」= 开始的日子；「计划 10-02」或「计划 10-02 08:00」= 计划完成（立项时定的，只写日期的算当天结束）；虚线「改到 …」= 改期后的",
                 "“Start 09-28” = the day it began; “Due 10-02” or “Due 10-02 08:00” = the planned finish set at creation (a date alone means end of that day); dashed “Moved to …” = after replanning"),
    "lg.life": ("底下的细线 = 目标从开始到现在（或结束）", "Thin line underneath = the goal from start to now (or to its end)"),
    "lg.future": ("虚线「还在做」= 没做完的事从现在往后：开着的环节同色，没分环节、眼下没环节开着的（等别人 / 暂停）灰色",
                  "Dashed “still going” line = unfinished work from now on: same color as the open stage; grey when there are no stages or none is open (waiting / paused)"),
    "lg.late": ("红框「延期 N 小时 / N 天」= 超出计划多久（不满一天按小时）", "Red box “N hours / N days late” = how far past plan (hours when under a day)"),
    "lg.done": ("✓ = 完成的那一刻，名称下面写「已完成 MM-DD」（灰 ✕ = 放弃）；已结束的事只在时间线拖到那段时才显示",
                "✓ = the moment it was done, with “Done MM-DD” under the name (grey ✕ = abandoned); ended goals show only when the timeline is dragged to their period"),
    "lg.version": ("蓝边小牌 = 这件事挂在哪个版本下，点了看版本", "Blue-outlined chip = the version this goal is attached to; click to open it"),
    "lg.helper": ("色块里「·人名」= 这段由负责人以外的人做", "“·name” inside a block = this span was done by someone other than the owner"),
    "lg.numbers": ("「G17」= 目标编号，「G17.2」= 从 G17 拆出来的第 2 块；号发出去就不变；后面的小字「· A24」= 出生号（本人字母＋序号），"
                   "和各人个人看板上那一行对得上，直接在这里立的没有。GitHub 单另有自己的「#174」",
                   "“G17” = goal number; “G17.2” = the 2nd part split from G17; numbers never change once issued. The small “· A24” after it = "
                   "source number (a person's letter + sequence) matching the row on that person's personal board; goals created here directly have none. "
                   "GitHub issues keep their own “#174”"),
    "lg.family": ("淡底色 = 同一个业务目标拆到了几条线，这些块是一家的；鼠标放上去整家一起亮",
                  "Light tint = one business goal split across several lines; these parts are one family and light up together on hover"),

    # ---------------------------------------------------------------- 口述框
    "dict.how": ("怎么用", "How it works"),
    "dict.how_text": ("：口述（用输入法的语音输入）或自己打字都行，把事情讲清楚就好；保存后会复制一段话，粘到 AI 对话框，AI 用看板的接口录进去，"
                      "缺什么会先问你。时间没说就按现在记，补录要说清哪天几点。录错了可以作废重录，看板只追加不删除。",
                      ": dictate (voice input works) or type, just say it clearly. Saving copies a prompt; paste it into your AI chat and the AI records it "
                      "through the board's API, asking first if anything is missing. No time given means now; for something in the past, say the day and hour. "
                      "Mistakes can be voided and re-recorded. The board only appends, never deletes."),
    "dict.can": ("你能录什么", "What you can record"),
    "dict.can_owner": ("：什么都能录——立项、换负责人、放弃、定版本计划，以及所有目标的进展。其他成员只能录自己负责的事；"
                       "他们要新开目标、或把事拆给别人做，AI 不会替他们录，会让他们来找团队负责人，由团队负责人口述立项。",
                       ": everything. Create goals, reassign, abandon, plan versions, and progress on any goal. Other members can only record their own work; "
                       "if they need a new goal or want to hand part of one to someone else, the AI won't record it and will send them to a team owner, "
                       "who dictates it."),
    "dict.can_member": ("：① 自己负责的目标：环节开始和结束、暂停和恢复、改计划完成日、标记完成；也能在它下面拆子目标给自己。"
                        "② 替别人做的环节（比如替负责人测试）：自己记这一段的开始和结束。"
                        "③ 新开一个目标、把事拆给别人做、换负责人、放弃：这些只有团队负责人能定。你口述里带了这类事，AI 不会录，"
                        "会提醒你去找团队负责人；定了，由团队负责人口述立项。",
                        ": (1) Goals you own: start and end stages, pause and resume, change the due date, mark done; you can also split sub-goals "
                        "under them for yourself. (2) A stage you do on someone else's goal (say, testing for the owner): record the start and end of your own span. "
                        "(3) Starting a new goal, handing work to someone else, reassigning, abandoning: only a team owner decides these. "
                        "If your dictation includes them, the AI won't record that part and will point you to a team owner, who then dictates it."),
    "dict.placeholder_goal": ("关于「{title}」的进展，直接写下来，例如：今天测出 5 个问题，回去改开发，测试同时继续……",
                              "Progress on “{title}”, in your own words. E.g. testing found 5 issues today, back to dev while testing continues…"),
    "dict.placeholder": ("进展或要立项的目标，直接写下来，例如：会员页今天测完了；或：周会定了，要做个……由谁负责、大概什么时候完成。",
                         "Progress, or a goal to start, in your own words. E.g. the membership screen finished testing today; "
                         "or: we agreed at the weekly to build …, who owns it, roughly when it's due."),
    "dict.placeholder_tail": ("保存后会复制一段话，粘贴到 AI 对话框，由 AI 录进看板；缺什么 AI 会先问你。",
                              "Saving copies a prompt. Paste it into your AI chat and the AI records it; it asks first if anything is missing."),
    "dict.save": ("保存并复制给 AI", "Save & copy for AI"),
    "dict.done": ("已录入", "Recorded"),
    "dict.waiting": ("待录入", "Pending"),
    "dict.about": ("关于 ", "about "),
    "dict.copy": ("复制给 AI", "Copy for AI"),
    "dict.resolved": ("{time} 录入：{summary}", "Recorded {time}: {summary}"),
    "dict.done_count": ("已录入 {n} 条", "{n} recorded"),
    "jsd.about": ("（关于目标 {num}「{title}」）", " (about goal {num} “{title}”)"),
    "jsd.prompt": ("请把下面这段口述录进团队看板（口述 #{id}）{about}。先看看板现状和操作说明；"
                   "缺信息就先问我，不要猜；录完把口述 #{id} 标记为已录入，并告诉我录了哪些。",
                   "Please record the dictation below on the team board (dictation #{id}){about}. Read the board state and the action reference first; "
                   "if anything is missing, ask me instead of guessing. When done, mark dictation #{id} as recorded and tell me what you recorded."),
    "jsd.prompt_practice": ("请把下面这段口述录进练手看板（练手口述 #{id}）{about}。这是练手，不是真的："
                            "所有看板操作都走练手看板（看板工具一律带 practice=true），不要碰正式看板，也不要推进个人看板。"
                            "先看练手看板现状和操作说明；缺信息就先问我，不要猜；录完把练手口述 #{id} 标记为已录入，并告诉我录了哪些。",
                            "Please record the dictation below on the PRACTICE board (practice dictation #{id}){about}. This is practice, not real: "
                            "do everything on the practice board (pass practice=true to every board tool), don't touch the real board and don't push "
                            "anything to a personal board. Read the practice board's state and the action reference first; if anything is missing, ask me "
                            "instead of guessing. When done, mark practice dictation #{id} as recorded and tell me what you recorded."),
    "jsd.copy_blocked": ("浏览器没让自动复制：下面这段已选中，按 ⌘C / Ctrl+C 复制。",
                         "The browser blocked automatic copy: the text below is selected, press ⌘C / Ctrl+C."),
    "jsd.empty": ("先写点内容", "Write something first"),
    "jsd.save_failed": ("没保存成功：{error}", "Could not save: {error}"),
    "jsd.saved": ("已保存为口述 #{id}，并复制好了，粘贴到 AI 对话框即可。刷新页面可在下面看到这条记录。",
                  "Saved as dictation #{id} and copied. Paste it into your AI chat. Refresh to see it listed below."),
    "jsd.copied": ("已复制口述 #{id}，粘贴到 AI 对话框即可。", "Dictation #{id} copied. Paste it into your AI chat."),

    # ---------------------------------------------------------------- 目标详情页
    "gp.back_board": ("← 回看板", "← Back to the board"),
    "gp.back_practice": ("← 回练手看板", "← Back to the practice board"),
    "gp.back_sample": ("← 回示例看板", "← Back to the sample board"),
    "gp.split_from_pre": ("从 ", "split from "),
    "gp.split_from_post": (" 拆出", ""),
    "gp.source": ("来源 {source}", "Source {source}"),
    "gp.source_tip": ("个人看板立项时发的出生号，一辈子不变；按它也能查到这个目标",
                      "The source number issued by a personal board at creation; it never changes and also finds this goal"),
    "gp.version_tip": ("点了看版本页", "Open the version page"),
    "gp.long_term": ("长期负责", "Ongoing"),
    "gp.sample_tag": ("示例（假设数据）", "Sample (hypothetical data)"),
    "gp.line_owner": ("{line} · 负责人 {owner}", "{line} · Owner: {owner}"),
    "gp.what": ("做什么", "What"),
    "gp.done_what": ("做了什么", "What was done"),
    "gp.why_abandoned": ("为什么放弃", "Why abandoned"),
    "gp.since": ("立项 {time}{tz}· 已 {total}", "Created {time}{tz} · {total} so far"),
    "gp.long_term_no_due": ("长期负责，不定完成日", "Ongoing, no finish date"),
    "gp.plan": ("计划 {due} 完成", "Due {due}"),
    "gp.plan_was": ("（原定 {due}）", " (was {due})"),
    "gp.not_late": ("没有延期", "Not late"),
    "gp.paused_since": ("{time}{tz}起暂停：{kind}", "Paused since {time}{tz}: {kind}"),
    "gp.pause_not_counted": ("。暂停期间不算环节耗时。", ". Paused time doesn't count toward any stage."),
    "gp.dragged_pre": ("被拖住：", "Held up: "),
    "gp.dragged_post": (" 拖过了计划完成日", " ran past this goal's due date"),
    "gp.stages": ("环节", "Stages"),
    "gp.running": ("（进行中）", " (in progress)"),
    "gp.spans": ("每一段的起止{tz}", "Each span, start to end{tz}"),
    "gp.no_stages": ("没分环节，只看起止（笼统的事项可以一直这样；要分环节时，开始记某个环节就行）。",
                     "No stages, just start and end (fine for broad goals; to track stages, just start one)."),
    "gp.children": ("拆出来的子目标", "Sub-goals"),
    "gp.deps": ("依赖", "Dependencies"),
    "gp.dep_pre": ("做到「{stage}」时需要 ", "At “{stage}” it needs "),
    "gp.dep_post": (" 完成", " to be done"),
    "gp.dep_their_plan": ("（对方计划 {due}）", " (theirs is due {due})"),
    "gp.links": ("关联的单", "Linked issues"),
    "gp.subcontract": ("分包 ", "Subcontract "),
    "gp.issue_closed": ("已关闭", "closed"),
    "gp.issue_now": ("现在：{state}（{dur}）", "now: {state} ({dur})"),
    "gp.sub_delivered": ("分包已交付，用了 {dur}", "delivered after {dur}"),
    "gp.sub_waiting": ("分包已等 {dur}", "waiting {dur}"),
    "gp.not_synced": ("还没同步到", "not synced yet"),
    "gp.dictation_sub": ("关于这个目标的进展，讲清楚交给 AI 录入", "Say what happened on this goal; the AI records it"),
    "gp.manual": ("手动修改（备用：AI 不在手边、或要马上改一个小地方时用）",
                  "Edit by hand (fallback: when no AI is at hand, or for a quick small fix)"),
    "gp.when": ("什么时候{tz}，不填=现在", "When{tz}; blank = now"),
    "gp.start": ("开始", "Start"),
    "gp.end": ("结束", "End"),
    "gp.stages_hint": ("几个环节可以同时进行、反复进出", "Stages can overlap and be re-entered"),
    "gp.due": ("计划完成", "Due date"),
    "gp.due_placeholder": ("2026-10-15 或 2026-10-15 08:00{tz}", "2026-10-15 or 2026-10-15 08:00{tz}"),
    "gp.why": ("为什么", "Why"),
    "gp.save": ("保存", "Save"),
    "gp.resume": ("恢复推进", "Resume"),
    "gp.resume_btn": ("恢复", "Resume"),
    "gp.pause": ("暂停", "Pause"),
    "gp.pause_which": ("等的是哪个目标（等依赖时选）", "Which goal it waits on (for a dependency)"),
    "gp.note": ("说明", "Note"),
    "gp.complete": ("完成", "Complete"),
    "gp.done_what_optional": ("做了什么（就是标题本身可不填）", "What was done (skip if the title says it all)"),
    "gp.complete_btn": ("标记完成", "Mark done"),
    "gp.complete_hint": ("业务验证通过才算完成", "Done means it passed business verification"),
    "gp.abandon": ("放弃", "Abandon"),
    "gp.abandon_btn": ("放弃这个目标", "Abandon this goal"),
    "gp.edit_summary": ("改概要（做什么；平时跟 AI 说一句就行）", "Edit the summary (What; normally just tell the AI)"),
    "gp.edit_summary_done": ("改概要（做什么 / 做了什么；平时跟 AI 说一句就行）",
                             "Edit the summary (What / What was done; normally just tell the AI)"),
    "gp.edit_hint": ("只改没动的不记；要清空跟 AI 说", "Unchanged fields aren't recorded; to clear one, ask the AI"),
    "gp.history": ("修改留痕（{n} 条；录错了可以作废那一条，作废也留痕）",
                   "History ({n} records; a wrong one can be voided, and the void is recorded too)"),
    "gp.backfill": ("补录", "backfilled"),
    "gp.voided": ("已作废：{reason}", "voided: {reason}"),
    "gp.void_why": ("为什么作废", "Why void it"),
    "gp.void": ("作废", "Void"),

    # ---------------------------------------------------------------- 留痕里每种记录怎么写
    "hist.sep": ("，", ", "),
    "hist.version_name": ("「{name}」", "“{name}”"),
    "hist.proposed": ("立项：{title}（{line}）", "Created: {title} ({line})"),
    "hist.proposed_long_term": ("，长期负责", ", ongoing"),
    "hist.proposed_version": ("，挂在版本 {version} 下", ", attached to version {version}"),
    "hist.proposed_source": ("，来源 {source}", ", source {source}"),
    "hist.approved": ("计划 {due} 完成", "Due {due}"),
    "hist.approved_no_due": ("计划完成日待定", "Due date to be decided"),
    "hist.assigned": ("负责人：{owner}", "Owner: {owner}"),
    "hist.stage_started": ("开始「{stage}」，执行人 {who}", "Started “{stage}”, done by {who}"),
    "hist.stage_ended": ("结束「{stage}」", "Ended “{stage}”"),
    "hist.edited": ("修改：", "Edited: "),
    "hist.edit.title": ("名称改为「{title}」", "renamed to “{title}”"),
    "hist.edit.note": ("「做什么」已更新", "“What” updated"),
    "hist.edit.done_what": ("「做了什么」已更新", "“What was done” updated"),
    "hist.edit.line": ("移到「{line}」", "moved to “{line}”"),
    "hist.edit.version": ("版本改为 {version}", "version set to {version}"),
    "hist.edit.version_none": ("不挂", "none"),
    "hist.edit.parent": ("改为从 {gnum} 拆出", "now split from {gnum}"),
    "hist.edit.parent_none": ("不再属于上层目标", "no longer under a parent goal"),
    "hist.edit.long_term_on": ("标为长期负责", "marked ongoing"),
    "hist.edit.long_term_off": ("不再是长期负责", "no longer ongoing"),
    "hist.edit.source": ("补上来源号 {source}", "source number {source} added"),
    "hist.dep_removed": ("解除对 {gnum} 的依赖", "Removed the dependency on {gnum}"),
    "hist.voided": ("作废第 {id} 条记录：{reason}", "Voided record {id}: {reason}"),
    "hist.note_added": ("口述录入：{text}", "Dictation: {text}"),
    "hist.note_resolved": ("标记口述 {id} 已录入：{summary}", "Marked dictation {id} as recorded: {summary}"),
    "hist.paused": ("暂停：{kind}", "Paused: {kind}"),
    "hist.paused_on": ("（等 {gnum}）", " (on {gnum})"),
    "hist.paused_note": ("，{note}", ", {note}"),
    "hist.resumed": ("恢复推进", "Resumed"),
    "hist.due_changed": ("改期到 {due}：{reason}", "Due date moved to {due}: {reason}"),
    "hist.dep_declared": ("声明依赖：做到「{stage}」时需要 {gnum} 完成", "Declared a dependency: at “{stage}” it needs {gnum} done"),
    "hist.dep_need_by": ("，最晚 {need}", ", by {need} at the latest"),
    "hist.issue_linked": ("关联单 {ref}", "Linked issue {ref}"),
    "hist.issue_linked_sub": ("关联分包单 {ref}", "Linked subcontract issue {ref}"),
    "hist.issue_unlinked": ("取消关联 {ref}", "Unlinked {ref}"),
    "hist.completed": ("标记完成", "Marked done"),
    "hist.completed_what": ("，写了「做了什么」", ", with “What was done”"),
    "hist.abandoned": ("放弃：{reason}", "Abandoned: {reason}"),
    "hist.version_tracked": ("加到看板上", "Added to the board"),
    "hist.version_planned": ("计划日期定为 {due}", "Planned date set to {due}"),
    "hist.version_prefill": ("（GitHub 预填）", " (prefilled from GitHub)"),

    # ---------------------------------------------------------------- 版本页
    "vp.milestone": ("{repo} 第 {number} 号里程碑", "{repo} milestone #{number}"),
    "vp.on_github": ("在 GitHub 上看", "View on GitHub"),
    "vp.not_synced": ("还没从 GitHub 同步到这个里程碑。", "This milestone hasn't been synced from GitHub yet."),
    "vp.on_board": ("在看板上", "On the board"),
    "vp.done_sep": ("，", ", "),
    "vp.done_at": ("已完成 {time}{tz}", "done {time}{tz}"),
    "vp.plan": ("计划日期（原定 / 现在）", "Planned date (original / current)"),
    "vp.gh_due": ("GitHub 上的截止日", "Due date on GitHub"),
    "vp.gh_due_empty": ("没填", "not set"),
    "vp.late": ("超出计划 {late}", "{late} past plan"),
    "vp.whats_new": ("这版做了什么", "What's in this version"),
    "vp.whats_new_empty": ("这个版本下还没有完成的目标。", "No goals done under this version yet."),
    "vp.spans": ("各环节跨度（版本下所有目标里，第一个进入到最后一个离开{tz}）",
                 "Stage spans (across this version's goals, first in to last out{tz})"),
    "vp.spans_empty": ("这个版本下还没有目标进入任何环节。", "No goal under this version has entered a stage yet."),
    "vp.goals": ("挂在这个版本下的目标", "Goals attached to this version"),
    "vp.moved_in": ("挪进来的单", "Issues moved in"),
    "vp.moved_out": ("挪出去的单", "Issues moved out"),
    "vp.moved_from": ("从 {src} 挪来", "from {src}"),
    "vp.moved_to": ("挪到 {dst}", "to {dst}"),
    "vp.removed": ("从版本里摘掉了", "removed from the version"),
    "vp.manual": ("手动修改（备用：平时口述交给 AI）", "Edit by hand (fallback: normally dictate to the AI)"),
    "vp.track": ("加到看板", "Add to the board"),
    "vp.plan_date": ("计划日期", "Planned date"),
    "vp.complete": ("版本完成", "Version done"),
    "vp.history": ("修改留痕（{n} 条）", "History ({n} records)"),

    # ---------------------------------------------------------------- GitHub 同步
    "gh.unmapped_label": ("未登记标签：{label}", "unmapped label: {label}"),
    "gh.deleted_label": ("（已删除的标签）", "(deleted label)"),
    "gh.busy": ("另一轮同步正在进行，请稍后再看", "Another sync is in progress; check back shortly"),
    "gh.http_error": ("GitHub 返回 HTTP {status}：{body}", "GitHub returned HTTP {status}: {body}"),
    "gh.network_error": ("连不上 GitHub：{error}", "Could not reach GitHub: {error}"),
    "gh.api_error": ("GitHub 返回错误：{error}", "GitHub returned an error: {error}"),
    "gh.gap_count": ("事件数对不上（取到 {got} 条，GitHub 报 {total} 条）", "event count mismatch (got {got}, GitHub reports {total})"),
    "gh.gap_labels": ("有标签但取不到状态记录", "has labels but no status history could be fetched"),
    "gh.fetch_failed": ("抓取失败：{error}", "fetch failed: {error}"),
    "gh.incomplete_item": ("{repo}#{number}：{reason}", "{repo}#{number}: {reason}"),

    # ---------------------------------------------------------------- 规则报错
    "err.unknown_params": ("不认识的参数：{names}", "Unknown parameter(s): {names}"),
    "err.missing": ("缺少 {key}", "Missing {key}"),
    "err.must_be_text": ("{key} 必须是文字", "{key} must be text"),
    "err.too_long": ("{key} 太长（最多 {n} 字）", "{key} is too long (max {n} characters)"),
    "err.one_of": ("{key} 只能是：{options}", "{key} must be one of: {options}"),
    "err.not_a_date": ("{key} 不是日期（要写成 2026-10-15）", "{key} is not a date (write it as 2026-10-15)"),
    "err.due_format": ("{key} 要写成 2026-10-15 或 2026-10-15 08:00{tz}", "{key} must look like 2026-10-15 or 2026-10-15 08:00{tz}"),
    "err.due_format_raw": ("计划完成要写成 2026-10-15 或 2026-10-15 08:00：{value}", "A due date must look like 2026-10-15 or 2026-10-15 08:00: {value}"),
    "err.must_be_int": ("{key} 必须是整数", "{key} must be an integer"),
    "err.must_be_positive": ("{key} 必须是正整数", "{key} must be a positive integer"),
    "err.must_be_flag": ("{key} 只能是 是 / 否", "{key} must be yes / no"),
    "err.no_goal": ("目标 {id} 不存在", "Goal {id} does not exist"),
    "err.goal_page_missing": ("目标不存在", "Goal not found"),
    "err.no_repo": ("没有这个仓库", "No such repo"),
    "err.team_owner_only": ("这个操作只有团队负责人能做（立项、换负责人、放弃、定版本计划）",
                            "Only a team owner can do this (create goals, reassign, abandon, plan versions)"),
    "err.goal_owner_only": ("只有负责人（{owner}）或团队负责人能改这个目标", "Only the owner ({owner}) or a team owner can change this goal"),
    "err.bad_status": ("目标{when}是「{status}」，不能做这个操作", "The goal is “{status}”{when}, so this isn't allowed"),
    "err.before_created": ("{gnum}「{title}」{time}{tz}才立项，不能补在它之前",
                           "{gnum} “{title}” was only created at {time}{tz}; nothing can be recorded before that"),
    "err.close_after_last": ("完成 / 放弃只能记在这个目标最后一条记录 {time}{tz} 之后",
                             "Completing / abandoning must come after this goal's last record at {time}{tz}"),
    "err.version_close_after_last": ("版本完成只能记在这个版本最后一条记录 {time}{tz} 之后",
                                     "Completing a version must come after its last record at {time}{tz}"),
    "err.github_off": ("这个操作要先在配置里开启 GitHub 同步（github.enabled，并写上仓库）",
                       "This needs GitHub sync turned on in the config (github.enabled, with repos)"),
    "err.version_ref": ("版本要写成「仓库#里程碑编号」，仓库只能是：{repos}", "A version is written repo#milestone-number; repo must be one of: {repos}"),
    "err.source_format": ("来源号要写成本人字母＋序号（{letters}），例如 {example}，收到 {value}",
                          "A source number is the person's letter + a sequence ({letters}), e.g. {example}; got {value}"),
    "err.source_taken": ("来源号 {source} 已经是 {gnum}「{title}」的了", "Source number {source} already belongs to {gnum} “{title}”"),
    "err.source_letter": ("来源号 {source} 是{letter_owner}的个人看板发的号，{me}推的要以 {letter} 开头",
                          "Source number {source} was issued by {letter_owner}'s personal board; what {me} pushes must start with {letter}"),
    "err.source_owner_only": ("补来源号只有团队负责人能做", "Only a team owner can add a source number afterwards"),
    "err.source_fixed": ("{gnum} 已经有来源号 {source}，出生号一辈子不变；补错了作废那条记录",
                         "{gnum} already has source number {source}; a source number never changes. If it was added by mistake, void that record"),
    "err.long_term_with_due": ("长期负责的事没有计划完成日；要定日期就不要标 long_term",
                               "An ongoing goal has no due date; drop long_term if you want one"),
    "err.long_term_has_due": ("这个目标已经定了计划完成日，不能再标成长期负责", "This goal already has a due date and can't be marked ongoing"),
    "err.long_term_unchanged": ("「长期负责」标记没有变", "The ongoing flag is unchanged"),
    "err.long_term_no_due": ("长期负责的事不定完成日；具体动作拆成带日期的子目标，或先去掉「长期负责」标记",
                             "An ongoing goal takes no due date; split concrete work into dated sub-goals, or clear the ongoing flag first"),
    "err.sample_under_sample": ("示例只能挂在示例下面", "A sample can only go under a sample"),
    "err.sample_mix_parent": ("示例和真实目标不能互相挂", "Samples and real goals can't be nested under each other"),
    "err.sample_mix_wait": ("示例和真实目标不能互相等", "Samples and real goals can't wait on each other"),
    "err.sample_mix_dep": ("示例和真实目标不能互相依赖", "Samples and real goals can't depend on each other"),
    "err.line_missing": ("缺少 line（顶层目标要写在哪条线）", "Missing line (a top-level goal needs a line)"),
    "err.create_top": ("立一个新的顶层目标只有团队负责人能做；你可以在自己负责的目标下面拆子目标",
                       "Only a team owner can create a new top-level goal; you can split sub-goals under goals you own"),
    "err.create_under_other": ("「{title}」的负责人是{owner}，只能在自己负责的目标下面拆",
                               "“{title}” is owned by {owner}; you can only split goals you own"),
    "err.create_for_other": ("拆出来的子目标只能由你自己负责；要交给别人做，找团队负责人立项指派",
                             "A sub-goal you split must be owned by you; to hand it to someone else, ask a team owner to create and assign it"),
    "err.before_parent": ("上层目标「{title}」{time}{tz}才立项，下层不能比它早",
                          "Parent goal “{title}” was only created at {time}{tz}; a sub-goal can't be earlier"),
    "err.owner_unchanged": ("负责人没有变", "The owner is unchanged"),
    "err.stage_for_other": ("只有负责人（{owner}）或团队负责人能替别人记环节；你可以记自己做的环节",
                            "Only the owner ({owner}) or a team owner can record a stage for someone else; you can record the ones you do yourself"),
    "err.assign_first": ("先指派负责人", "Assign an owner first"),
    "err.stage_running": ("「{stage}」{at}已经在进行", "“{stage}” is already in progress{at}"),
    "err.stage_not_running": ("「{stage}」{at}没有在进行", "“{stage}” is not in progress{at}"),
    "err.no_such_dep": ("没有这个依赖", "No such dependency"),
    "err.done_what_early": ("{gnum} {then}还没完成：「做了什么」在完成时写（补录要记在完成之后）；放弃的原因写在放弃里",
                            "{gnum} was not done yet{then}: “What was done” is written on completion (a backfill must come after it); the reason for abandoning goes with the abandon"),
    "err.already_top": ("这个目标本来就不属于任何上层", "This goal has no parent already"),
    "err.already_under": ("已经挂在 {gnum}「{title}」下面", "Already under {gnum} “{title}”"),
    "err.cycle": ("不能挂到自己或自己的下层目标下面", "A goal can't go under itself or one of its own sub-goals"),
    "err.same_line": ("已经在「{line}」", "Already on “{line}”"),
    "err.nothing_to_change": ("没有要改的内容", "Nothing to change"),
    "err.no_note": ("口述 {id} 不存在", "Dictation {id} does not exist"),
    "err.note_resolved": ("这条口述已经标记过已录入", "This dictation is already marked as recorded"),
    "err.no_event": ("记录 {id} 不存在", "Record {id} does not exist"),
    "err.already_voided": ("这条记录已经作废，或本身就是作废记录", "This record is already voided, or is itself a void"),
    "err.void_not_yours": ("只有原记录人或团队负责人能作废这条记录", "Only whoever recorded it, or a team owner, can void this record"),
    "err.void_has_records": ("这个目标后面还有记录或子目标；要撤掉请用「放弃」，或先作废后面的记录",
                             "This goal has later records or sub-goals; abandon it instead, or void the later records first"),
    "err.void_depended": ("{names} 还依赖或等着这个目标，先解除依赖 / 恢复推进再撤",
                          "{names} still depend(s) on or wait(s) for this goal; remove the dependency / resume first"),
    "err.already_paused": ("已经在暂停中", "Already paused"),
    "err.pause_after_last": ("后面已经有暂停记录，暂停只能补在最后一次暂停之后", "There is a later pause; a pause can only be backfilled after the last one"),
    "err.pause_needs_goal": ("等依赖要写清等哪个目标（depends_on）", "Waiting on a dependency needs the goal it waits for (depends_on)"),
    "err.wait_self": ("不能等自己", "A goal can't wait on itself"),
    "err.depends_only_dependency": ("只有「等依赖」才填 depends_on", "depends_on only applies to waiting on a dependency"),
    "err.not_paused": ("{at}没有在暂停", "Not paused{at}"),
    "err.same_due": ("和那时的预计完成日一样", "Same as the due date at that point"),
    "err.depend_self": ("不能依赖自己", "A goal can't depend on itself"),
    "err.dep_exists": ("已经声明过这个依赖", "This dependency is already declared"),
    "err.issue_linked": ("这张单已经关联过了", "This issue is already linked"),
    "err.issue_not_linked": ("这张单没有关联", "This issue is not linked"),
    "err.paused_resume_first": ("目标在暂停中，先恢复", "The goal is paused; resume it first"),
    "err.children_open": ("还有子目标没结束", "Some sub-goals are still open"),
    "err.parent_before_child": ("上层目标不能比下层先完成：{gnum}「{title}」{time}{tz}才结束",
                                "A parent can't be done before its sub-goals: {gnum} “{title}” only ended at {time}{tz}"),
    "err.goal_ended": ("目标已经结束", "The goal has already ended"),
    "err.version_tracked": ("这个版本已经在看板上了", "This version is already on the board"),
    "err.version_track_first": ("先把这个版本加到看板上", "Add this version to the board first"),
    "err.version_before_tracked": ("这个版本 {time}{tz}才加到看板上，不能补在它之前",
                                   "This version was only added at {time}{tz}; nothing can be recorded before that"),
    "err.version_same_due": ("和那时的计划日期一样", "Same as the planned date at that point"),
    "err.version_untracked": ("这个版本不在看板上", "This version is not on the board"),
    "err.version_done": ("这个版本已经标记完成", "This version is already marked done"),
    "err.week_monday": ("week_start 要填那一周的周一", "week_start must be the Monday of that week"),
    "err.url_https": ("链接要以 https:// 开头", "The link must start with https://"),
    "err.no_action": ("没有这个操作：{action}", "No such action: {action}"),
    "err.not_on_roster": ("不在看板名单里", "Not on the board's roster"),
    "err.params_object": ("params 必须是对象", "params must be an object"),
    "err.occurred_at": ("occurred_at 必须是带时区的时间，例如 2026-09-28T10:00:00-07:00",
                        "occurred_at must carry a UTC offset, e.g. 2026-09-28T10:00:00-07:00"),
    "err.future": ("发生时间不能晚于现在", "The time can't be in the future"),
    "err.inconsistent": ("这次修改和已有记录对不上，已撤销：{detail}", "This change contradicts existing records and was rolled back: {detail}"),
    "err.unfoldable": ("这次修改会让看板算不出来（后面还有记录用到它），已撤销（{kind}）",
                       "This change would break the board (later records rely on it) and was rolled back ({kind})"),
    "err.backfill_time": ("补录时间格式不对", "Bad time format"),
    "err.body_not_json": ("请求体不是 JSON", "The request body is not JSON"),
    "err.body_shape": ("格式：{{\"action\": \"...\", \"params\": {{...}}}}", "Expected: {{\"action\": \"...\", \"params\": {{...}}}}"),
    "err.resolve_miss": ("看板上没有 {num} 这个号：来源号写本人字母＋序号（例 A16），G 号写 G27 或 G2.5",
                         "No goal numbered {num}: a source number is a person's letter + sequence (e.g. A16); a G number looks like G27 or G2.5"),
    "err.resolve_empty": ("（空）", "(empty)"),
    "fold.void_target": ("作废对象不存在或本身是作废记录：{id}", "the voided record doesn't exist or is itself a void: {id}"),
    "fold.source_dup": ("来源号 {source} 重复：{a} 和 {b}", "source number {source} used twice: {a} and {b}"),
    "fold.stage_not_running": ("「{stage}」没有在进行，不能结束", "“{stage}” is not in progress, so it can't end"),
    "fold.not_paused": ("没有在暂停，不能恢复", "not paused, so it can't resume"),

    # ---------------------------------------------------------------- 操作说明（GET /api/board/actions）
    "act.occurred_at": ("补录时间，带时区的 ISO，例如 2026-09-28T10:00:00-07:00；不填=现在",
                        "When it actually happened, ISO with a UTC offset, e.g. 2026-09-28T10:00:00-07:00; omit for now"),
    "act.create.desc": (
        "立项一个目标（提议、要不要做在周会或私下谈，定了才进看板）。"
        "parent_id 填它从哪个目标拆出来（不填 line 就跟上层同一条线；一个业务目标可以拆到别的线，那就填 line）；"
        "due 是计划完成（主时区），写 2026-10-15 或精确到小时 2026-10-15 08:00，可以先不定；"
        "不分环节的笼统事项照样建，不记环节就行。"
        "long_term=1 表示长期负责的事（例如长期盯崩溃率）：没有完成日，看板上显示「长期」，具体动作再拆成带日期的子目标。"
        "sample=1 表示演示用的假设数据（只在示例看板上显示），录真实进度不要填。"
        "source 是来源号：从个人看板推上来的目标，填它在个人看板立项时发的出生号（本人字母＋序号，字母见取值表 source_letters），"
        "字母要和推的人对得上；全看板唯一，一辈子不变，按它能查到这个目标（GET /api/board/resolve?num=…）。团队看板上直接立的不填。"
        "note 是「做什么」（详情页标题下显示，500 字以内）：AI 自判写不写、不问人——没参与的人只看标题能知道要达成什么、"
        "做到什么算完就空着；不能就写一到两句：要达成什么结果 + 怎么算达成（能验证的判据，不写实现）",
        "Create a goal (whether to do it is settled elsewhere; only decided goals go on the board). "
        "parent_id is the goal it is split from (without line it stays on the parent's line; a business goal may split onto another line, then pass line). "
        "due is the planned finish in the primary time zone: 2026-10-15, or to the hour 2026-10-15 08:00; it may be left open. "
        "A broad goal with no stages is fine: just don't record stages. "
        "long_term=1 marks an ongoing responsibility (e.g. watching the crash rate): no finish date, shown as “Ongoing”; split concrete work into dated sub-goals. "
        "sample=1 marks hypothetical demo data (shown only on the sample board); never set it for real progress. "
        "source is the source number: for a goal pushed up from a personal board, the number that board issued at creation (the person's letter + sequence; "
        "letters are in values.source_letters). The letter must match whoever pushes it. It is unique across the board, never changes, and finds the goal "
        "(GET /api/board/resolve?num=…). Leave it out for goals created here directly. "
        "note is the “What” (shown under the title, up to 500 characters): the AI decides whether to write it, without asking. Leave it empty when the title alone "
        "tells an outsider what is to be achieved and when it counts as done; otherwise one or two sentences: the outcome, and how to tell it's reached "
        "(a checkable criterion, not the implementation)"),
    "act.create.who": ("团队负责人（owner 角色）；负责人可以在自己负责的目标下面拆子目标给自己（拆给别人、另开一棵仍只有团队负责人能做）",
                       "Team owners (role owner); a goal's owner may split sub-goals under their own goal for themselves "
                       "(assigning to someone else, or starting a new tree, stays with team owners)"),
    "act.assign.desc": ("换负责人", "Change the owner"),
    "act.assign.who": ("团队负责人", "Team owners"),
    "act.start_stage.desc": ("开始一个环节，可以和别的环节同时进行、反复进出；executor 不填就是记录人自己（负责人或团队负责人不填时是负责人）",
                             "Start a stage; stages can overlap and be re-entered. Without executor it is whoever records it "
                             "(the goal's owner, when the owner or a team owner records it)"),
    "act.start_stage.who": ("负责人或团队负责人；替别人做这个环节的人也能记自己那一段",
                            "The owner or a team owner; someone doing this stage for the owner may record their own span"),
    "act.end_stage.desc": ("结束一个正在进行的环节", "End a stage that is in progress"),
    "act.end_stage.who": ("负责人或团队负责人；这段的执行人也能结束自己做的那一段",
                          "The owner or a team owner; whoever is doing the span may end their own"),
    "act.pause.desc": ("暂停（kind：dependency 等依赖 / external 等外部），暂停期间不算环节耗时",
                       "Pause (kind: dependency = waiting on another goal / external = waiting on someone outside); paused time isn't counted toward stages"),
    "act.pause.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.resume.desc": ("恢复推进", "Resume"),
    "act.resume.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.change_due.desc": ("改计划完成（写 2026-10-15 或 2026-10-15 08:00，主时区；还没定过时，第一次填的就是基准）",
                            "Change the due date (2026-10-15 or 2026-10-15 08:00, primary time zone; the first one ever set becomes the baseline)"),
    "act.change_due.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.declare_dependency.desc": ("声明：做到某环节时需要另一个目标完成（need_by 可选：最晚哪天要）",
                                    "Declare that at a given stage this goal needs another goal done (need_by optional: needed by when)"),
    "act.declare_dependency.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.remove_dependency.desc": ("解除一个依赖", "Remove a dependency"),
    "act.remove_dependency.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.link_issue.desc": ("关联 GitHub 单（kind：link 普通 / subcontract 分包）", "Link a GitHub issue (kind: link = plain / subcontract)"),
    "act.link_issue.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.unlink_issue.desc": ("取消关联 GitHub 单", "Unlink a GitHub issue"),
    "act.unlink_issue.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.edit_goal.desc": (
        "改名称、说明、挂的版本、从哪个目标拆出来（parent_id；填 - 表示不属于任何上层；改上层和换线只有团队负责人能做），"
        "换线（原来同一条线的下层跟着走），或改「长期负责」标记（long_term=1/0）；"
        "source 给早先从个人看板推上来、当时没带来源号的目标补上出生号（只有团队负责人能补，已有来源号的不能改——补错了作废那条记录）；"
        "note / done_what 改「做什么 / 做了什么」（填空 = 清空；done_what 只能写在已完成的目标上）",
        "Change the title, the note, the attached version, the parent (parent_id; - means no parent; only team owners may change the parent or the line), "
        "the line (sub-goals on the same line follow), or the ongoing flag (long_term=1/0). "
        "source adds a source number to a goal that was pushed up earlier without one (team owners only; an existing one can't be changed, void the record if it was wrong). "
        "note / done_what edit “What / What was done” (empty clears it; done_what only on a goal that is done)"),
    "act.edit_goal.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.complete.desc": (
        "完成（业务验证通过）。done_what 是「做了什么」（1000 字以内，详情页显示、版本页汇总）：AI 自判写不写、不问人——"
        "照应用商店的 What's new 写，用简洁通俗的话概括用的人看得见的变化，条数不限，不写过程、审查、测试条数、提交号；"
        "完成的东西就是标题本身、没别的可说就空着",
        "Complete (business verification passed). done_what is “What was done” (up to 1000 characters; shown on the goal page and summed up on the version page): "
        "the AI decides whether to write it, without asking. Write it like an app store's What's New: plain words for the changes users can see, as many lines as needed, "
        "no process, reviews, test counts or commit ids. Leave it empty when the title already says it all"),
    "act.complete.who": ("负责人或团队负责人", "The owner or a team owner"),
    "act.abandon.desc": ("放弃（reason 写为什么）", "Abandon (reason says why)"),
    "act.abandon.who": ("团队负责人", "Team owners"),
    "act.track_version.desc": ("把一个 GitHub 里程碑加到看板上", "Add a GitHub milestone to the board"),
    "act.track_version.who": ("所有人", "Everyone"),
    "act.plan_version.desc": ("定或改版本的计划完成（写 2026-10-15 或 2026-10-15 08:00，主时区）",
                              "Set or change a version's planned date (2026-10-15 or 2026-10-15 08:00, primary time zone)"),
    "act.plan_version.who": ("团队负责人", "Team owners"),
    "act.complete_version.desc": ("版本完成", "Mark a version done"),
    "act.complete_version.who": ("所有人", "Everyone"),
    "act.link_weekly.desc": ("登记某一周的周会文档（week_start 是那周的周一）", "Register the weekly-meeting notes for a week (week_start is that week's Monday)"),
    "act.link_weekly.who": ("所有人", "Everyone"),
    "act.add_note.desc": ("口述录入：保存一段原始进展（再复制给 AI 录入）；goal_id 表示是关于哪个目标的",
                          "Dictation: save a raw progress note (then copy it to the AI to record); goal_id says which goal it is about"),
    "act.add_note.who": ("所有人", "Everyone"),
    "act.resolve_note.desc": ("AI 录完后，标记这条口述已录入，写一句录了什么", "After recording, mark the dictation as recorded with one sentence on what was recorded"),
    "act.resolve_note.who": ("所有人", "Everyone"),
    "act.void.desc": ("作废一条录错的记录（只追加不删除，作废也留痕）；作废建目标那条 = 撤掉整个目标（只在它还没有后续记录时可以）",
                      "Void a wrong record (append-only: the void is recorded too). Voiding a goal's creation withdraws the whole goal (only while it has no later records)"),
    "act.void.who": ("原记录人或团队负责人", "Whoever recorded it, or a team owner"),

    # ---------------------------------------------------------------- MCP
    "mcp.bad_url": ("{env} 只能是本机 http://127.0.0.1:端口 或 https:// 地址（令牌不走明文 http 出本机）",
                    "{env} must be a local http://127.0.0.1:port address or an https:// address (tokens never leave the machine over plain http)"),
    "mcp.unreachable": ("连不上看板 {base}：{reason}。本机的看板没在跑的话先启动它（python3 -m team_board start）",
                        "Could not reach the board at {base}: {reason}. If it runs on this machine, start it first (python3 -m team_board start)"),
    "mcp.not_json": ("看板返回 HTTP {status}，不是 JSON：{body}", "The board returned HTTP {status}, not JSON: {body}"),
    "mcp.rejected": ("看板拒绝（HTTP {status}）：{reason}", "The board refused (HTTP {status}): {reason}"),
    "mcp.need_token": ("要在环境变量 {env} 里放你的个人令牌", "put your personal token in the {env} environment variable"),
    "mcp.no_notes_field": ("看板现状接口没有口述清单（notes 字段），读不到口述 #{id} 是谁写的；先问人：这条口述是谁写的、原文是什么（粘贴来的那段就是原文）",
                           "The board state has no dictation list (no notes field), so dictation #{id} can't be read; ask the person who wrote it and what it says (the pasted text is the original)"),
    "mcp.no_note": ("口述 #{id} 不存在", "Dictation #{id} does not exist"),
    "mcp.no_second_zone": ("看板没有配第二时区，zone 只能用 primary", "The board has no second time zone; zone can only be primary"),
    "mcp.time_now": ("现在", "now"),
    "mcp.both_join": ("= ", " = "),
    "mcp.bad_when": ("when 要写成 2026-09-29 14:30（按 zone 解释）或带时区偏移的 ISO 时间",
                     "when must look like 2026-09-29 14:30 (read in the given zone) or an ISO time with a UTC offset"),
    "mcp.arg.practice": ("true = 练手看板（/board/practice，数据是正式看板的副本，不是真的）；口述没说「练手」就不传",
                         "true = the practice board (/board/practice, a copy of the real board, not real); omit unless the dictation says “practice”"),
    "mcp.arg.note_id": ("口述编号，即「口述 #N」的 N", "The dictation number: the N in “dictation #N”"),
    "mcp.arg.when": ("2026-09-29 14:30 或带时区偏移的 ISO", "2026-09-29 14:30, or ISO with a UTC offset"),
    "mcp.arg.zone": ("when 按哪个时区解释：primary 主时区（缺省）/ second 第二时区（看板配了才有）；人没明确说就用 primary",
                     "Which zone to read when in: primary (default) / second (only if the board has one); use primary unless the person says otherwise"),
    "mcp.arg.action": ("board_actions 列出的操作名", "An action name listed by board_actions"),
    "mcp.arg.params": ("该操作的参数；补录加 occurred_at（带时区）", "The action's parameters; add occurred_at (with UTC offset) for something in the past"),
    "mcp.tool.actions": ("看板操作说明（唯一来源）：每个操作做什么、谁能做、必填/选填字段，以及线、环节、人、角色、暂停种类、仓库的取值表，"
                         "还有「我是谁」（me：这个连接的令牌是谁的）。追问缺什么以它为准。只读。",
                         "The board's action reference (single source of truth): what each action does, who may do it, required/optional fields, "
                         "the allowed values (lines, stages, people, roles, pause kinds, repos), and who you are (me: whose token this connection uses). "
                         "Use it to decide what to ask for. Read-only."),
    "mcp.tool.guide": ("录入手册全文（身份、追问、列操作清单请人确认后再写、写完回读、标记已录入、录错了怎么办、不要做的事）和版本号。"
                       "有的客户端只显示 MCP 说明的前两千字左右，开始录入前先读这里。只读。",
                       "The full recording guide (identity, what to ask, confirming the action list before writing, reading back, marking as recorded, "
                       "fixing mistakes, what not to do) and its version. Some clients show only the first couple of thousand characters of the MCP instructions, "
                       "so read this before recording. Read-only."),
    "mcp.tool.state": ("看板现状：全部目标（id、编号、线、负责人、上层目标、状态、进行中的环节、计划完成日、延期天数）、卡点、口述清单、我是谁。只读。",
                       "The board's current state: every goal (id, number, line, owner, parent, status, open stages, due date, days late), blockers, "
                       "the dictation list, and who you are. Read-only."),
    "mcp.tool.note": ("按编号读一条口述：原文、谁写的（who / who_key）、关于哪个目标、是否已录入。只读。",
                      "Read one dictation by number: the text, who wrote it (who / who_key), which goal it is about, whether it is recorded. Read-only."),
    "mcp.tool.time": ("时间换算（用时区库，别心算）：不传 when 给现在；传「2026-09-29 14:30」和 zone，返回看板时区的写法"
                      "（配了第二时区就两地都给）、请人确认用的一行（both）和可直接填 occurred_at 的时间。只读。",
                      "Time conversion (uses a tz database; don't do it in your head): no when = now; pass “2026-09-29 14:30” and zone to get it in the board's time zone "
                      "(both zones if a second one is configured), a one-line form for confirming with the person (both), and a value ready for occurred_at. Read-only."),
    "mcp.tool.act": ("往看板写一个操作（create、start_stage、end_stage、change_due、pause、resume、declare_dependency、complete、abandon、edit_goal、void……）。"
                     "以这个连接的令牌所属的人的身份写。params 原样交给看板校验：缺、多、错都会被拒绝，报错原样带回。"
                     "成功返回 event_ids 和 goal_id。会写看板，写前先把操作清单给人确认。",
                     "Write one action to the board (create, start_stage, end_stage, change_due, pause, resume, declare_dependency, complete, abandon, edit_goal, void, …). "
                     "It is written as the person whose token this connection uses. params go to the board as-is: anything missing, extra or wrong is rejected and the error comes back verbatim. "
                     "Returns event_ids and goal_id. This writes; confirm the action list with the person first."),
    "mcp.tool.resolve_note": ("录完后把口述 #N 标记为已录入，summary 一句话写录了什么。会写看板。",
                              "After recording, mark dictation #N as recorded; summary says in one sentence what was recorded. This writes."),
    "mcp.args_unknown": ("{tool} 不认识的参数：{names}", "{tool}: unknown argument(s): {names}"),
    "mcp.args_missing": ("{tool} 缺少参数：{names}", "{tool}: missing argument(s): {names}"),
    "mcp.args_type": ("{tool} 的 {key} 类型不对，要 {type}", "{tool}: {key} has the wrong type, expected {type}"),
    "mcp.args_enum": ("{tool} 的 {key} 只能是：{options}", "{tool}: {key} must be one of: {options}"),
    "mcp.args_positive": ("{tool} 的 {key} 必须是正整数", "{tool}: {key} must be a positive integer"),
    "mcp.no_tool": ("没有这个工具：{name}", "No such tool: {name}"),
    "mcp.no_method": ("不支持的方法：{method}", "Method not supported: {method}"),
    "mcp.no_guide": ("录入手册不在：{path}（MCP 的说明来自它，缺了不启动）", "Guide not found: {path} (the MCP instructions come from it; refusing to start without it)"),
    "mcp.check.board": ("看板：{base}", "Board: {base}"),
    "mcp.check.me": ("我是：{name}（{role}）", "I am: {name} ({role})"),
    "mcp.check.guide": ("手册：{path}（{n} 字）", "Guide: {path} ({n} chars)"),
    "mcp.check.actions": ("看板操作 {n} 个；人：{people}", "{n} board actions; people: {people}"),
    "mcp.check.practice": ("练手看板：通（{n} 个目标）", "Practice board: OK ({n} goals)"),
    "mcp.check.tools": ("工具：{names}", "Tools: {names}"),

    # ---------------------------------------------------------------- 命令行
    "cli.desc": ("团队看板：init 生成配置 → seed 灌示例数据 → start 起服务；mcp 给 AI 用",
                 "Team Board: init writes a config → seed loads demo data → start runs the server; mcp is for your AI"),
    "cli.cmd.init": ("生成配置文件（含每个人的随机个人令牌）", "Write a config file (with a random personal token per person)"),
    "cli.cmd.seed": ("往空看板里灌一份虚构团队的示例数据", "Load a fictional team's demo data into an empty board"),
    "cli.cmd.start": ("起看板服务", "Run the board server"),
    "cli.cmd.act": ("从终端读写看板：state / actions 只读，其余操作要 --execute", "Read or write the board from a terminal: state / actions are read-only, everything else needs --execute"),
    "cli.cmd.mcp": ("看板的 MCP 服务（stdio），给 Claude Code / Codex 等用", "The board's MCP server (stdio), for Claude Code, Codex and the like"),
    "cli.cmd.find": ("给任意一个目标号（来源号 / G27 / G2.5），找回相关提交与 Issue（只读）",
                     "Given any goal number (source number / G27 / G2.5), find its commits and issues (read-only)"),
    "cli.cmd.backup": ("把正式库在线备份成一个文件（服务不用停）", "Back up the real database to a file, online (no need to stop the server)"),
    "cli.cmd.people": ("列出配置里的人、角色和个人令牌", "List the people, roles and personal tokens in the config"),
    "cli.mcp.desc": ("团队看板的 MCP 服务（stdio）。不带参数就作为 MCP 服务跑在 stdin/stdout 上",
                     "Team Board's MCP server (stdio). Without arguments it serves MCP on stdin/stdout"),
    "cli.mcp.url": ("看板地址；缺省取环境变量 {env}，再缺省本机配置里的地址", "Board URL; default: ${env}, then the address in the local config"),
    "cli.mcp.check": ("只读自检后退出，不进入 MCP 服务", "Run a read-only self-check and exit"),
    "cli.mcp.no_url": ("没有看板地址：设 {env} 或传 --url（本机也没有配置文件）", "No board URL: set {env} or pass --url (no local config file either)"),
    "cli.arg.config": ("配置文件路径（缺省取环境变量 TEAM_BOARD_CONFIG，再缺省 ~/.config/team-board/config.json）",
                       "Config file path (default: $TEAM_BOARD_CONFIG, then ~/.config/team-board/config.json)"),
    "cli.arg.lang": ("语言：zh / en", "Language: zh / en"),
    "cli.arg.data_dir": ("数据目录（缺省 ~/.local/share/team-board）", "Data directory (default ~/.local/share/team-board)"),
    "cli.arg.port": ("端口（缺省 10890）", "Port (default 10890)"),
    "cli.arg.host": ("监听地址（缺省取配置；免登录的本地试用模式只能是 127.0.0.1）", "Listen address (default from config; local no-login mode allows only 127.0.0.1)"),
    "cli.arg.timezone": ("主时区的 IANA 名，例如 Europe/Berlin（缺省取本机时区）", "Primary time zone, IANA name, e.g. Europe/Berlin (default: this machine's)"),
    "cli.arg.timezone_label": ("主时区在页面上的叫法", "Display label for the primary time zone"),
    "cli.arg.second_timezone": ("第二时区（可选）：配了之后请人确认时刻时两地都写", "Second time zone (optional): when set, times are confirmed in both"),
    "cli.arg.second_timezone_label": ("第二时区在页面上的叫法", "Display label for the second time zone"),
    "cli.arg.auth": ("登录方式：local 本地试用免登录（缺省）/ token 个人令牌", "Sign-in mode: local = no login, for trying out (default) / token = personal tokens"),
    "cli.arg.force": ("配置文件已存在也覆盖（令牌会全部重新生成）", "Overwrite an existing config (all tokens are regenerated)"),
    "cli.arg.practice": ("操作练手看板而不是正式看板", "Use the practice board instead of the real one"),
    "cli.arg.seed_practice": ("重做练手库并把示例数据灌进去（不碰正式库）", "Rebuild the practice database and load the demo data into it (the real one is untouched)"),
    "cli.arg.execute": ("真正写入；不带只打印将发送的内容", "Actually write; without it, only print what would be sent"),
    "cli.arg.param": ("操作的参数，可以写多次", "A parameter of the action; repeatable"),
    "cli.arg.as": ("以谁的身份（配置里的人的 id）：用本机配置文件里他的令牌。缺省用环境变量 TEAM_BOARD_TOKEN",
                   "Act as this person (an id from the config), using their token from the local config file. Default: $TEAM_BOARD_TOKEN"),
    "cli.arg.url": ("看板地址（缺省取环境变量 TEAM_BOARD_URL，再缺省本机配置里的地址）", "Board URL (default: $TEAM_BOARD_URL, then the address in the local config)"),
    "cli.arg.action": ("state | actions | sync | 或操作说明里列出的任一操作（create、start_stage……）",
                       "state | actions | sync | or any action from the reference (create, start_stage, …)"),
    "cli.arg.out": ("备份放到哪个目录（缺省：数据目录下的 board/backups）", "Directory for the backup (default: board/backups under the data directory)"),
    "cli.arg.num": ("来源号（例 A16）、永久号 G27 或显示号 G2.5", "A source number (e.g. A16), a permanent number G27, or a display number G2.5"),
    "cli.arg.repo": ("在哪个 git 仓库目录里翻提交（缺省当前目录）", "The git checkout to search for commits (default: current directory)"),
    "cli.init.exists": ("配置文件已经存在：{path}（要覆盖加 --force；覆盖会重新生成所有令牌）",
                        "Config already exists: {path} (use --force to overwrite; that regenerates every token)"),
    "cli.init.done": ("已生成配置：{path}", "Config written: {path}"),
    "cli.init.people": ("人和个人令牌（令牌只在这个文件里，别提交到仓库、别发到群里）：", "People and personal tokens (they live only in this file; don't commit or post them):"),
    "cli.init.next": ("下一步：\n  python3 -m team_board seed      # 可选：灌一份虚构团队的示例数据\n  python3 -m team_board start     # 打开 {url}\n"
                      "把人、线、环节换成自己的：直接改这个 JSON 文件，然后重启。",
                      "Next:\n  python3 -m team_board seed      # optional: load a fictional team's demo data\n  python3 -m team_board start     # then open {url}\n"
                      "To use your own people, lines and stages, edit that JSON file and restart."),
    "cli.seed.done": ("已灌入示例数据：{n} 个目标 → {path}", "Demo data loaded: {n} goals → {path}"),
    "cli.seed.refused": ("{path} 里已经有目标，示例数据只往空看板里灌（想在练手看板上看示例：加 --practice）",
                         "{path} already has goals; demo data only goes into an empty board (to see it on the practice board, add --practice)"),
    "cli.start.listening": ("{title}：{url}（登录方式 {auth}，数据在 {data}）", "{title}: {url} (auth: {auth}, data in {data})"),
    "cli.act.param_format": ("--param 要写成 键=值，收到 {item}", "--param must be key=value, got {item}"),
    "cli.act.param_dup": ("--param {key} 重复了", "--param {key} given twice"),
    "cli.act.no_params": ("{action} 不接受 --param", "{action} takes no --param"),
    "cli.act.no_person": ("本机配置里没有这个人：{id}", "No such person in the local config: {id}"),
    "cli.act.no_url": ("没有看板地址：设 TEAM_BOARD_URL 或传 --url", "No board URL: set TEAM_BOARD_URL or pass --url"),
    "cli.act.dry": ("[只打印] 将 POST {url}", "[dry run] would POST {url}"),
    "cli.act.dry_hint": ("加 --execute 才会真正写入", "Add --execute to actually write"),
    "cli.backup.no_db": ("还没有正式库：{path}", "No database yet: {path}"),
    "cli.backup.done": ("已备份：{path}", "Backed up: {path}"),
    "cli.find.bad_num": ("认不出 {num}：写来源号（本人字母＋序号）、永久号（G27）或显示号（G2.5）",
                         "Can't parse {num}: use a source number (letter + sequence), a permanent number (G27) or a display number (G2.5)"),
    "cli.find.miss": ("看板上没有 {num}", "The board has no {num}"),
    "cli.find.head": ("{num} → {gnum}「{title}」（{owner}，{status}）", "{num} → {gnum} “{title}” ({owner}, {status})"),
    "cli.find.same": ("  同一个目标：显示号 {gnum}、永久号 {permanent}、{source}", "  Same goal: display number {gnum}, permanent number {permanent}, {source}"),
    "cli.find.source": ("来源号 {source}", "source number {source}"),
    "cli.find.no_source": ("没有来源号（直接在团队看板上立的）", "no source number (created on the team board directly)"),
    "cli.find.commits": ("\n相关提交（{n}）：提交信息里有一行「Board-Goal: {nums}」的", "\nCommits ({n}): those whose message has a line “Board-Goal: {nums}”"),
    "cli.find.issues": ("\n相关 Issue（{n}）：看板上和这个目标关联的单", "\nIssues ({n}): those linked to this goal on the board"),
    "cli.find.nothing": ("  没有", "  none"),
    "cli.find.git_failed": ("  翻提交失败（这里不是 git 仓库？）：{error}", "  Could not search commits (not a git checkout?): {error}"),
    "cli.people.row": ("{id}\t{name}\t{role}\t出生号字母 {letter}\t令牌 {token}", "{id}\t{name}\t{role}\tsource letter {letter}\ttoken {token}"),
}


# ---------------------------------------------------------------- 取用

_default = "zh"
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("team_board_lang", default=None)


def set_default(lang: str) -> None:
    global _default
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}, got {lang!r}")
    _default = lang


def activate(lang: str):
    return _current.set(lang)


def deactivate(token) -> None:
    _current.reset(token)


def current_lang() -> str:
    return _current.get() or _default


def html_lang(lang: str | None = None) -> str:
    return _HTML_LANG[lang or current_lang()]


def tr(lang: str, key: str, /, **kw) -> str:
    return M[key][_IDX[lang]].format(**kw)


def t(key: str, /, **kw) -> str:
    return tr(current_lang(), key, **kw)


def unit(n, name: str) -> str:
    """带单位的数：unit("1.5", "day") → 「1.5 天」/ "1.5 days"（英文只有正好 1 才用单数）。"""
    n = str(n)
    return t(f"unit.{name}" if n == "1" else f"unit.{name}s", n=n)


def js_strings(prefix: str) -> dict[str, str]:
    """页面脚本要用的那几条（键以 prefix 开头），原样给出，占位符由脚本自己填。"""
    i = _IDX[current_lang()]
    return {k: v[i] for k, v in M.items() if k.startswith(prefix)}
