import importlib.util
from pathlib import Path

from test_agents import argon, project, pytestmark  # reuse required live-stack fixture


def test_two_agents_same_pin_review_and_undo(argon, project):
    spec = importlib.util.spec_from_file_location("two_agent_review", Path(__file__).parents[1] / "examples/two_agent_review.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # run_review creates its own project; the fixture guarantees the stack exists.
    result = module.run_review(argon, project + "-example")
    assert result["reviewed_price"] == 44
    assert result["restored_price"] == 49
