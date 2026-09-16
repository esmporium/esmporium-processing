"""
Tests that every use case builds, serialises, compiles and can be satisfied
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from tests.unit.requirements.helpers import satisfying_catalog
from tests.unit.requirements.use_cases import USE_CASES

import esmporium_processing.requirements
from esmporium_processing.requirements import Requirement, solve, to_search_plan


@pytest.mark.parametrize("requirement", USE_CASES.values(), ids=USE_CASES.keys())
def test_use_case(requirement):
    loaded = Requirement.model_validate_json(requirement.model_dump_json())
    assert loaded.requirement_hash() == requirement.requirement_hash()

    plan = to_search_plan(requirement)
    assert plan.queries

    res = solve(requirement, satisfying_catalog(requirement))

    assert len(res.resolved) == 1, res.explain()
    assert not (res.unsatisfied or res.ambiguous or res.undetermined)


def test_requirements_package_can_move_to_esmporium():
    """
    The requirements package may only import from itself, esmporium,
    pydantic and the standard library
    """
    package_dir = Path(esmporium_processing.requirements.__file__).parent
    allowed = {"esmporium", "pydantic", "__future__"} | sys.stdlib_module_names

    offending = []
    for path in sorted(package_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                continue

            for module in modules:
                if module.startswith("esmporium_processing.requirements"):
                    continue

                if module.split(".")[0] not in allowed:
                    offending.append(f"{path.name}: {module}")

    assert not offending
