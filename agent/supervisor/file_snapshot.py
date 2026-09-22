"""文件级回滚快照（dev-notes/software-development-agent-phase.md「文件级回滚」）。

零依赖的产物文件备份/恢复，供 Supervisor 在验收失败时恢复被误删/误改的文件：

    write_snapshot(snapshot_dir, tree_root)
        把 tree_root 下受管理的产物文件（agent/src/tests/scripts 前缀、
        不超过 1MB、跳过 .git/.venv 等目录）复制进 snapshot_dir，
        并用 _INDEX 记录「快照名 -> 源相对路径」映射。
    restore_snapshot(snapshot_dir, tree_root)
        按 _INDEX 把文件逐个写回 tree_root；全部成功后删除 snapshot_dir，
        防止旧快照被重复恢复造成污染。
    snapshot_paths(snapshot_dir)
        只读 _INDEX 返回源相对路径，用于发布事件/审计（不动文件）。

设计约束：
- 只备份、只恢复：不删除快照建立后新出现的文件（防误删/误改，不回收新增）。
- 内容按字节原样读写（read_bytes/write_bytes），不做文本转换、不碰 git。
- 快照名由相对路径 parts 拼接生成（空格转下划线），重名追加序号；
  真实源路径只保存在 _INDEX 里。
- 恢复时拒绝越界路径（绝对路径或含 ..），与 workspace 隔离安全模型一致。
- 快照目录建议放在 output_dir 之外，避免被扫描进后续快照。
"""

from __future__ import annotations

import shutil
from pathlib import Path

_INDEX = "_INDEX.txt"
_INDEX_HEADER = "# file-snapshot v1: <snapshot_name><TAB><source_rel_path>"

# 与 agent/codebase/analyzer.py 保持一致的忽略目录（零依赖约定）
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", "dist", "build"}
# 只备份这些顶层目录下的文件（产物目录，防止把无关文件卷进快照）
_ROOT_PREFIXES = ("agent", "src", "tests", "scripts")
# 单文件上限：超大文件（模型权重/构建产物）不值得逐次备份
_MAX_BYTES = 1024 * 1024


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _iter_source_files(
    tree_root: Path, skip_root: Path | None = None
) -> tuple[tuple[Path, str], ...]:
    """收集受管理的产物文件：(源路径, 相对路径)；跳过忽略目录与超大文件。"""
    files: list[tuple[Path, str]] = []
    if not tree_root.is_dir():
        return ()
    for path in tree_root.rglob("*"):
        if skip_root is not None and _is_within(path, skip_root):
            continue
        rel = path.relative_to(tree_root)
        rel_parts = rel.parts
        if not rel_parts or rel_parts[0] not in _ROOT_PREFIXES:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
        except OSError:
            continue
        files.append((path, rel.as_posix()))
    files.sort(key=lambda item: item[1])
    return tuple(files)


def _snapshot_name(rel: str, used: set[str]) -> str:
    """相对路径 -> 快照文件名（parts 拼接、空格转下划线，重名追加序号）。"""
    base = "_".join(Path(rel).parts).replace(" ", "_")
    name = base
    seq = 2
    while name in used:
        name = f"{base}~{seq}"
        seq += 1
    used.add(name)
    return name


def write_snapshot(snapshot_dir: Path, tree_root: Path) -> tuple[str, ...]:
    """备份 tree_root 下的产物文件到 snapshot_dir；返回备份成功的源相对路径。

    每次调用清空重写 snapshot_dir，保证重试前拿到的永远是当前最新状态。
    """
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir, ignore_errors=True)
    files = _iter_source_files(tree_root, snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if not files:
        return ()
    used: set[str] = set()
    saved: list[str] = []
    index_lines = [_INDEX_HEADER]
    for source, rel in files:
        name = _snapshot_name(rel, used)
        try:
            data = source.read_bytes()
        except OSError:
            continue
        try:
            (snapshot_dir / name).write_bytes(data)
        except OSError:
            continue
        saved.append(rel)
        index_lines.append(f"{name}\t{rel}")
    if saved:
        (snapshot_dir / _INDEX).write_text(
            "\n".join(index_lines) + "\n", encoding="utf-8"
        )
    return tuple(saved)


def _read_index(snapshot_dir: Path) -> tuple[tuple[str, str], ...]:
    """读取 (快照名, 源相对路径) 映射；索引缺失/损坏时返回空。"""
    index_path = snapshot_dir / _INDEX
    if not index_path.is_file():
        return ()
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    entries: list[tuple[str, str]] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        name, _, rel = line.partition("\t")
        if not name or not rel:
            continue
        entries.append((name, rel))
    return tuple(entries)


def snapshot_paths(snapshot_dir: Path) -> tuple[str, ...]:
    """返回快照覆盖的源相对路径（只读索引，不恢复文件）。"""
    return tuple(rel for _, rel in _read_index(snapshot_dir))


def restore_snapshot(snapshot_dir: Path, tree_root: Path) -> tuple[str, ...]:
    """把快照文件写回 tree_root；全部成功（或无需恢复）后删除 snapshot_dir。

    恢复是「只写不改删」：只还原快照内的文件，不删除快照建立后
    新增的文件（防误删/误改，不回收新增）。
    """
    if not snapshot_dir.is_dir():
        return ()
    entries = _read_index(snapshot_dir)
    if not entries:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        return ()
    restored: list[str] = []
    failed = False
    for name, rel in entries:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            failed = True
            continue
        source = snapshot_dir / name
        try:
            data = source.read_bytes()
        except OSError:
            failed = True
            continue
        target = tree_root / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError:
            failed = True
            continue
        restored.append(rel)
    if not failed:
        # 删除快照目录，防止旧快照被重复恢复污染
        shutil.rmtree(snapshot_dir, ignore_errors=True)
    return tuple(restored)