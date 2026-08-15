"""TerminalTool Windows 命令翻译层测试（本机为 Windows，os.name == 'nt'）。"""

from __future__ import annotations

from pathlib import Path

from agent.tools.terminal import TerminalTool, translate_command


def test_translate_common_unix_commands() -> None:
    assert translate_command("pwd") == "cd"
    assert translate_command("ls -la") == "dir"
    assert translate_command("cat hello.py") == "type hello.py"
    assert translate_command("python3 hello.py") == "python hello.py"
    assert translate_command("mkdir -p src/x") == "mkdir src/x"
    assert translate_command("grep token auth.py") == "findstr token auth.py"
    assert translate_command("cp a.py b.py") == "copy a.py b.py"
    assert translate_command("mv a.py b.py") == "move a.py b.py"
    assert translate_command("touch empty.txt") == "type nul > empty.txt"


def test_translate_does_not_touch_windows_commands() -> None:
    assert translate_command("dir") == "dir"
    assert translate_command("python app.py") == "python app.py"
    assert translate_command("type README.md") == "type README.md"


def test_translate_keeps_pipeline_intact() -> None:
    assert translate_command("cat log.txt | grep error") == "type log.txt | findstr error"


def test_terminal_touch_creates_file(tmp_path: Path) -> None:
    tool = TerminalTool(cwd=tmp_path)
    result = tool.run(command="touch hello.txt")
    assert result.ok
    assert (tmp_path / "hello.txt").is_file()


def test_terminal_translated_rm_still_blocked(tmp_path: Path) -> None:
    tool = TerminalTool(cwd=tmp_path)
    result = tool.run(command="rm notes.txt")
    assert not result.ok
    assert "blocked by safety policy" in result.output