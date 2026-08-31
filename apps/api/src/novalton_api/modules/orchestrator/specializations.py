"""Typed specialization dispatch for the fixed I-028 workflow only."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import ContractEnforcementGrade
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents.contract_execution import ResultShapeConstraint
from novalton_api.modules.agents.contracts import AgentResult, ModelRequirementHints
from novalton_api.modules.agents.schemas import AgentExecutionResponse
from novalton_api.modules.developer_manager import service as manager_service
from novalton_api.modules.developer_manager.contracts import DeveloperManagerResult
from novalton_api.modules.developer_manager.schemas import DeveloperManagerPlanningRequest
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.developer_worker.contracts import (
    DeveloperWorkerResult,
)
from novalton_api.modules.developer_worker.schemas import DeveloperWorkerExecutionRequest
from novalton_api.modules.qa_worker import service as qa_service
from novalton_api.modules.qa_worker.contracts import ValidationCriterion
from novalton_api.modules.qa_worker.schemas import QAWorkerValidationRequest
from novalton_api.modules.workflows import repository
from novalton_api.modules.workflows.models import (
    WorkflowRun,
    WorkflowStep,
    WorkflowStepHandoff,
    WorkflowStepRun,
)

FIXED_MANAGER_RESULT_CONSTRAINTS: tuple[ResultShapeConstraint, ...] = (
    ResultShapeConstraint.exact_items(
        code="fixed_manager_task_count",
        path="development_plan.proposed_tasks",
        count=1,
    ),
    ResultShapeConstraint.empty(
        code="fixed_manager_task_dependencies_empty",
        path="development_plan.proposed_tasks[0].depends_on",
    ),
)

# The fixed development workflow needs one evidence source only.  The broader
# Developer Worker registry remains available to explicitly authorized direct
# assignments, but this orchestrator never widens that authority.
_DEVELOPMENT_WORKFLOW_DEVELOPER_TOOLS = ("workspace.read_file",)


@dataclass(frozen=True)
class SpecializedExecution:
    response: AgentExecutionResponse
    role: str


def _trusted(definition: object, service: object) -> bool:
    prefix = (
        "QA_WORKER"
        if service is qa_service
        else ("DEVELOPER_MANAGER" if service is manager_service else "DEVELOPER_WORKER")
    )
    expected_permissions = (
        developer_service.DEVELOPER_WORKER_PERMISSIONS if service is developer_service else []
    )
    expected_version = 2 if service is developer_service else 1
    return (
        getattr(definition, "version", None) == expected_version
        and getattr(definition, "name", None) == getattr(service, f"{prefix}_NAME")
        and getattr(definition, "category", None) == getattr(service, f"{prefix}_CATEGORY")
        and getattr(definition, "mission", None) == getattr(service, f"{prefix}_MISSION")
        and getattr(definition, "capabilities", None) == getattr(service, f"{prefix}_CAPABILITIES")
        and getattr(definition, "permissions", None) == expected_permissions
        and getattr(definition, "status", None) == "ENABLED"
    )


async def _input_handoff(
    session: AsyncSession, run: WorkflowRun, step_run: WorkflowStepRun, expected: str
) -> WorkflowStepHandoff:
    handoff = await repository.handoff_for_destination(
        session, run_id=run.id, destination_step_run_id=step_run.id
    )
    if (
        handoff is None
        or handoff.workflow_plan_id != run.workflow_plan_id
        or handoff.handoff_type != expected
    ):
        raise ApplicationError(
            "workflow_handoff_invalid", "Required workflow handoff is unavailable", status_code=409
        )
    return handoff


async def dispatch(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
) -> SpecializedExecution | None:
    """Dispatch only a fully trusted fixed-graph step; otherwise retain generic behavior."""
    graph = await repository.ordered_step_runs(session, run_id=run.id)
    if [(item.step_key, item.position) for _, item in graph] != [
        ("manager_plan", 0),
        ("developer_execute", 1),
        ("qa_validate", 2),
    ]:
        return None
    expected = {
        "manager_plan": (0, manager_service, "DEVELOPMENT_REQUEST", "developer_manager"),
        "developer_execute": (1, developer_service, "MANAGER_ASSIGNMENT", "developer_worker"),
        "qa_validate": (2, qa_service, "WORKER_EVIDENCE", "qa_worker"),
    }.get(step.step_key)
    if expected is None:
        return None
    position, specialization, handoff_type, role = expected
    definition = await specialization.resolve_definition(
        session, tenant_id=run.tenant_id, workspace_id=run.workspace_id
    )
    if (
        step.position != position
        or step.agent_definition_id != definition.id
        or not _trusted(definition, specialization)
    ):
        raise ApplicationError(
            "workflow_specialization_invalid",
            "Trusted workflow specialization is invalid",
            status_code=409,
        )
    handoff = await _input_handoff(session, run, step_run, handoff_type)
    permitted_tools = (
        list(_DEVELOPMENT_WORKFLOW_DEVELOPER_TOOLS) if role == "developer_worker" else []
    )
    common = dict(
        objective=handoff.objective,
        constraints=[
            "Requested actions are proposals only",
            (
                "Use only the explicitly permitted read-only workspace tools"
                if permitted_tools
                else "Do not use tools or execute external actions"
            ),
            "Remain within the fixed persisted workflow step",
            *[f"Trusted handoff metadata: {item}" for item in handoff.evidence_items],
        ],
        project_id=str(run.project_id),
        task_id=str(run.task_id),
        prior_result_references=[str(handoff.id)],
        permitted_tools=permitted_tools,
        model_requirements=ModelRequirementHints(
            required_capabilities=[step.assigned_capability] if step.assigned_capability else [],
            minimum_contract_enforcement_grade=ContractEnforcementGrade.PROVIDER_ENFORCED,
        ),
    )
    if role == "developer_manager":
        response = await manager_service.plan(
            session,
            registry=registry,
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
            data=DeveloperManagerPlanningRequest(**common),
            result_shape_constraints=FIXED_MANAGER_RESULT_CONSTRAINTS,
        )
    elif role == "developer_worker":
        response = await developer_service.execute_assignment(
            session,
            registry=registry,
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
            data=DeveloperWorkerExecutionRequest(**common),
        )
    else:
        response = await qa_service.validate(
            session,
            registry=registry,
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
            data=QAWorkerValidationRequest(
                **common,
                acceptance_criteria=[
                    ValidationCriterion(criterion_id=f"criterion_{index:02d}", description=value)
                    for index, value in enumerate(handoff.acceptance_criteria, start=1)
                ],
            ),
        )
    return SpecializedExecution(response=response, role=role)


async def persist_next_handoff(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    result: AgentResult,
) -> WorkflowStepHandoff | None:
    ordered = await repository.ordered_step_runs(session, run_id=run.id)
    index = next(i for i, (value, _) in enumerate(ordered) if value.id == step_run.id)
    if index + 1 >= len(ordered):
        return None
    destination = ordered[index + 1][0]
    current = await _input_handoff(
        session,
        run,
        step_run,
        "DEVELOPMENT_REQUEST"
        if isinstance(result, DeveloperManagerResult)
        else "MANAGER_ASSIGNMENT",
    )
    if isinstance(result, DeveloperManagerResult):
        proposals = result.development_plan.proposed_tasks
        if len(proposals) != 1 or proposals[0].depends_on:
            raise ApplicationError(
                "manager_plan_incompatible",
                "Manager proposal is incompatible with the fixed workflow",
                status_code=409,
            )
        proposal = proposals[0]
        handoff_type = "MANAGER_ASSIGNMENT"
        evidence = [f"task:{proposal.task_key}", f"output:{proposal.expected_output}"] + [
            f"capability:{value}" for value in proposal.required_capabilities
        ]
    elif isinstance(result, DeveloperWorkerResult):
        handoff_type = "WORKER_EVIDENCE"
        evidence = [
            f"acceptance:{item.criterion_id}:{item.status.value}"
            for item in result.acceptance_checks
        ] + [f"change:{item.kind.value}:{item.path}" for item in result.changes]
    else:
        return None
    handoff = WorkflowStepHandoff(
        workflow_run_id=run.id,
        workflow_plan_id=run.workflow_plan_id,
        source_step_run_id=step_run.id,
        destination_step_run_id=destination.id,
        handoff_type=handoff_type,
        objective=current.objective,
        acceptance_criteria=current.acceptance_criteria,
        evidence_items=evidence[:29],
    )
    return await repository.add_handoff(session, handoff)
