#!/usr/bin/env python3
"""从任何目录都能跑的入口：`python3 /path/to/team-board/tb.py <命令>`，等同于在本目录里 `python3 -m team_board <命令>`。

MCP 注册用它（MCP 客户端从别的目录启动进程）。mcp / act / find / people 这几个命令只用标准库，不装依赖也能跑。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from team_board.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
