import pytest

from src.orchestrator.engine import (
    DEFAULT_MAX_DELEGATION_DEPTH,
    DelegationDepthExceeded,
    OrchestrationEngine,
)


class TestDelegationDepth:
    def setup_method(self):
        self.engine = OrchestrationEngine(max_delegation_depth=3)

    def test_default_engine_uses_documented_max_depth(self):
        engine = OrchestrationEngine()
        assert engine.max_delegation_depth == DEFAULT_MAX_DELEGATION_DEPTH

    def test_construction_rejects_non_positive_max_depth(self):
        with pytest.raises(ValueError):
            OrchestrationEngine(max_delegation_depth=0)
        with pytest.raises(ValueError):
            OrchestrationEngine(max_delegation_depth=-1)

    def test_task_without_depth_is_treated_as_zero(self):
        task = {"id": "t1", "target_agent": "a1"}
        # No exception raised; depth is implicitly 0.
        self.engine._check_delegation_depth(task)

    def test_task_at_limit_is_rejected_before_execution(self):
        # max_delegation_depth=3 means depths 0,1,2 are allowed and 3 is rejected.
        ok_task = {"id": "t-ok", "target_agent": "a1", "delegation_depth": 2}
        bad_task = {"id": "t-bad", "target_agent": "a1", "delegation_depth": 3}
        self.engine._check_delegation_depth(ok_task)
        with pytest.raises(DelegationDepthExceeded) as exc:
            self.engine._check_delegation_depth(bad_task)
        assert exc.value.task_id == "t-bad"
        assert exc.value.depth == 3
        assert exc.value.limit == 3

    def test_invalid_depth_values_are_rejected(self):
        with pytest.raises(ValueError):
            self.engine._check_delegation_depth(
                {"id": "t", "target_agent": "a", "delegation_depth": -1}
            )
        with pytest.raises(ValueError):
            self.engine._check_delegation_depth(
                {"id": "t", "target_agent": "a", "delegation_depth": "five"}
            )

    def test_build_delegated_task_increments_depth(self):
        parent = {"id": "root", "target_agent": "a1", "delegation_depth": 1}
        child = {"id": "child", "target_agent": "a2", "payload": {"k": 1}}
        delegated = self.engine.build_delegated_task(parent, child)
        assert delegated["delegation_depth"] == 2
        assert delegated["delegated_from"] == "root"
        assert delegated["target_agent"] == "a2"
        assert delegated["payload"] == {"k": 1}
        # Parent and original child were not mutated.
        assert parent["delegation_depth"] == 1
        assert "delegation_depth" not in child

    def test_build_delegated_task_rejects_at_limit(self):
        parent = {"id": "root", "target_agent": "a1", "delegation_depth": 2}
        child = {"id": "child", "target_agent": "a2"}
        with pytest.raises(DelegationDepthExceeded) as exc:
            self.engine.build_delegated_task(parent, child)
        assert exc.value.task_id == "root"
        assert exc.value.depth == 3
        assert exc.value.limit == 3

    def test_build_delegated_task_preserves_existing_delegated_from(self):
        parent = {"id": "root", "target_agent": "a1", "delegation_depth": 0}
        child = {
            "id": "child",
            "target_agent": "a2",
            "delegated_from": "external-system",
        }
        delegated = self.engine.build_delegated_task(parent, child)
        assert delegated["delegated_from"] == "external-system"
