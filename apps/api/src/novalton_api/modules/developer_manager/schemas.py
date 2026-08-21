"""HTTP contracts for proposal-only Developer Manager planning."""

from pydantic import ConfigDict

from novalton_api.modules.agents.schemas import AgentExecutionResponse
from novalton_api.modules.developer_manager.contracts import (
    DeveloperManagerResult,
    DevelopmentPlanningInput,
)


class DeveloperManagerPlanningRequest(DevelopmentPlanningInput):
    pass


class DeveloperManagerPlanningResponse(AgentExecutionResponse):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result: DeveloperManagerResult | None = None
