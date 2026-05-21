import pytest

from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
    WorkflowValidationError,
)


def test_parallel_branch_steps_require_output_namespaces():
    manager = WorkflowManager()
    workflow = manager.create_workflow("branching")

    with pytest.raises(WorkflowValidationError):
        workflow.add_step(
            WorkflowStep("branch-a", lambda: {"value": 1}, branch="a")
        )

    assert workflow.status == StepStatus.PENDING
    assert workflow.steps == []


def test_duplicate_branch_output_namespaces_are_rejected():
    manager = WorkflowManager()
    workflow = manager.create_workflow("branching")

    workflow.add_step(
        WorkflowStep(
            "branch-a",
            lambda: {"value": 1},
            branch="a",
            output_namespace="branch",
        )
    )

    with pytest.raises(WorkflowValidationError):
        workflow.add_step(
            WorkflowStep(
                "branch-b",
                lambda: {"value": 2},
                branch="b",
                output_namespace="branch",
            )
        )

    assert [step.name for step in workflow.steps] == ["branch-a"]


def test_join_rejects_unknown_or_duplicate_namespaces_before_dispatch():
    manager = WorkflowManager()
    workflow = manager.create_workflow("branching")
    workflow.add_step(
        WorkflowStep(
            "branch-a",
            lambda: {"value": 1},
            branch="a",
            output_namespace="branch-a",
        )
    )

    with pytest.raises(WorkflowValidationError):
        workflow.add_step(
            WorkflowStep(
                "join",
                lambda: {"joined": True},
                join_inputs=["branch-a", "branch-a"],
            )
        )

    with pytest.raises(WorkflowValidationError):
        workflow.add_step(
            WorkflowStep(
                "join",
                lambda: {"joined": True},
                join_inputs=["missing-branch"],
            )
        )

    assert manager.execute_workflow(workflow.id)
    assert workflow.status == StepStatus.COMPLETED


def test_branch_outputs_are_visible_only_by_namespace():
    manager = WorkflowManager()
    workflow = manager.create_workflow("branching")
    workflow.add_step(
        WorkflowStep(
            "branch-a",
            lambda: {"value": "from-a"},
            branch="a",
            output_namespace="branch-a",
        )
    )
    workflow.add_step(
        WorkflowStep(
            "branch-b",
            lambda: {"value": "from-b"},
            branch="b",
            output_namespace="branch-b",
        )
    )
    workflow.add_step(
        WorkflowStep(
            "join",
            lambda: {"joined": True},
            join_inputs=["branch-a", "branch-b"],
        )
    )

    assert manager.execute_workflow(workflow.id)

    assert workflow.outputs == {
        "branch-a": {"value": "from-a"},
        "branch-b": {"value": "from-b"},
    }
    assert "value" not in workflow.outputs


def test_validation_audit_excludes_branch_payloads():
    manager = WorkflowManager()
    workflow = manager.create_workflow("branching")
    workflow.add_step(
        WorkflowStep(
            "branch-a",
            lambda: {"token": "secret-token"},
            branch="a",
            output_namespace="branch-a",
        )
    )

    assert manager.execute_workflow(workflow.id)

    decisions = manager.validation_decisions()
    assert decisions
    assert "secret-token" not in repr(decisions)
    assert decisions[-1]["reason"] == "workflow_outputs_namespaced"
