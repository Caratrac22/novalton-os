"""HTTP contracts for one bounded Developer Worker assignment."""

from pydantic import ConfigDict

from novalton_api.modules.agents.schemas import AgentExecutionResponse
from novalton_api.modules.developer_worker.contracts import (
    DeveloperWorkerResult,
    DevelopmentAssignmentInput,
)


class DeveloperWorkerExecutionRequest(DevelopmentAssignmentInput):
    pass


class DeveloperWorkerExecutionResponse(AgentExecutionResponse):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result: DeveloperWorkerResult | None = None
