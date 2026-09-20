"""Shared fixtures.

Every path is derived from this file's location so the suite passes from any
working directory, including CI runners that invoke pytest from the repo root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_MARKDOWN = """# 口腔医院互联互通项目上线总结

## 封面

天津市口腔医院信息化项目上线总结
2026 年度

## 项目概况

- 覆盖 5 个院区，服务 92 人团队
- 互联互通四甲评审通过
- 数据抽取成功率 99.2%

## 下阶段重点

- 推进专病数据库建设，首批聚焦种植科与口腔癌
- 固化自动化部署流程，覆盖信创环境

## 总结

- 上线目标按期达成
"""


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def cases_dir(repo_root: Path) -> Path:
    return repo_root / "benchmarks" / "cases"


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture()
def sample_markdown() -> str:
    return SAMPLE_MARKDOWN


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    comp_dir = tmp_path / 'components'
    elem_dir = tmp_path / 'elements'
    comp_dir.mkdir(exist_ok=True)
    elem_dir.mkdir(exist_ok=True)
    monkeypatch.setattr('ppt_agent.component_store.store_dir', lambda: comp_dir)
    monkeypatch.setattr('ppt_agent.element_store.store_dir', lambda: elem_dir)
