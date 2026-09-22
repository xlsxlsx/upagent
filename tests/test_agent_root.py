"""Regression tests for frozen-aware AGENT_ROOT resolution."""

import agent.core.agent as agent_module


def test_unfrozen_uses_repo_root() -> None:
    root = agent_module._resolve_agent_root()
    assert (root / "roles" / "architect.md").is_file()
    assert root.name == "agent"


def test_frozen_prefers_exe_side_agent_dir(monkeypatch, tmp_path) -> None:
    exe_dir = tmp_path / "exe"
    exe_side = exe_dir / "agent"
    exe_side.mkdir(parents=True)

    monkeypatch.setattr(agent_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(agent_module.sys, "executable", str(exe_dir / "UpAgent.exe"))
    monkeypatch.setattr(
        agent_module.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False
    )

    assert agent_module._resolve_agent_root() == exe_side


def test_frozen_falls_back_to_bundle(monkeypatch, tmp_path) -> None:
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir()
    bundle = tmp_path / "bundle"
    bundle_agent = bundle / "agent"
    bundle_agent.mkdir(parents=True)

    monkeypatch.setattr(agent_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(agent_module.sys, "executable", str(exe_dir / "UpAgent.exe"))
    monkeypatch.setattr(agent_module.sys, "_MEIPASS", str(bundle), raising=False)

    assert agent_module._resolve_agent_root() == bundle_agent
