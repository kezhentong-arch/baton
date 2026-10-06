# 一棒到底 · AI 协作手册

[English](README.md)

「一棒到底」是 AI 时代小团队的一种协作方式：**一件事，谁发起，谁负责到底**。负责人带着 AI 自己做完业务、产品、UI、开发、测试五个环节，
人和人之间的交接是例外。

这个目录里是写给 AI 编程助手（Claude Code、Codex 这一类）看的手册，教它在这种方式下怎么配合负责人。

## 里面有什么

```
zh/baton-owner/                 中文
  SKILL.md                      主手册：五个环节、检查点、整包与分包、收尾沉淀
  references/
    stage-business.md           业务：把要达成什么说清，立项、拆块
    stage-product-design.md     产品与 UI：文档与原型，原型是锚
    stage-dev.md                开发：先跑起来，自测过才算完
    stage-test.md               测试：列清单、真操作，测试和开发一起结束
en/baton-owner/                 英文，结构相同
```

AI 在用得上的时候读 `SKILL.md`，进到哪个环节才读哪本分册。中文、英文选一种装，两种装好后的名字都是 `baton-owner`。

## 怎么装

**Claude Code**：把整个文件夹复制到个人的技能目录，或某个项目里。

```bash
# 只给自己用，所有项目生效
mkdir -p ~/.claude/skills && cp -r zh/baton-owner ~/.claude/skills/

# 或者放进某个仓库，在这个仓库里干活的人都生效
mkdir -p /path/to/repo/.claude/skills && cp -r zh/baton-owner /path/to/repo/.claude/skills/
```

新开一个对话即可，Claude Code 会按手册开头的 `description` 判断什么时候用它。

**Codex**：把文件夹放到仓库里任意位置（例如 `docs/skills/baton-owner/`），在 `AGENTS.md` 里引用：

```markdown
## 和负责人配合
负责人自己做一件事的全流程（立项、产品方案、原型、开发、测试、收尾）时，
先读 `docs/skills/baton-owner/SKILL.md` 并照做；
进到哪个环节，再读 `references/` 下对应的那一本。
```

其他能读 Markdown 说明的 AI 助手，用法相同。

## 和两个看板的手册是什么关系

一棒到底配了两个看板，各有一本给 AI 的手册：

| | 管什么 | MCP 服务 / 工具 | 它的手册 |
|---|---|---|---|
| [个人看板](../personal-board/) | 一个人和他的各个 AI 对话 | `personal-board` / `personal_board_*` | `personal_board_guide` |
| [团队看板](../team-board/) | 团队里人和人之间 | `team-board` / `board_*` | `board_guide` |

分工是这样的：

- **看板手册管「怎么记」**：对话怎么归类、结果怎么记、环节起止、怎么推到团队看板。它们由各自的 MCP 服务直接下发给 AI
  （连接时作为说明下发，也可以调 guide 工具读全文），不用另外安装。
- **本手册管「怎么做」**：每个环节要产出什么、什么算做完、什么时候停下来问负责人、哪些交给别人做、每一轮该留下什么经验。
  它只提到看板的工具名，不重复看板的规则。

不装看板也能用本手册，留痕换成团队自己的方式即可。只装看板、不装本手册也能记，但没有人告诉 AI 一个环节「做到什么算完」。

## 换成你们自己的

这是通用底稿。在 `SKILL.md` 第九节加上你们团队的人和偏好，然后让它自己长：每轮收尾，AI 会提出值得留下的经验，
负责人确认后才写进对应的分册。
