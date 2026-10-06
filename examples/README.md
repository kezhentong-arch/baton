# Examples · 示例

`making-of.en.json` / `making-of.zh.json` are a real personal-board record: the days in which the Baton method, the team board and the personal board went from idea to launch, by one owner working with Claude Code (13 goals, 174 entries). From the first line of code to both boards live took under two days, about one day of it actual development; more than ten small versions followed within a day of launch. Names are replaced with the demo team's and internal addresses are removed; everything else is as it was recorded.

Load it into an empty personal board:

```bash
cd ../personal-board
./board init --name Alex --letter C
./board seed --case ../examples/making-of.en.json --adopt-config
./board start
```

`making-of.zh.json` 是一份真实的个人看板记录：这套协作方式、团队看板和个人看板，由一个负责人用 Claude Code 从立项做到上线的那几天（13 个目标、174 条记录）。从动手开发到两个看板都上线不到两天，实际开发时间约一天；上线后一天之内又迭代了十多个小版本。人名换成了示例团队的名字，内部地址已去掉，其余照原样。

```bash
cd ../personal-board
./board init --lang zh --name 林夏 --letter C
./board seed --case ../examples/making-of.zh.json --adopt-config
./board start
```
