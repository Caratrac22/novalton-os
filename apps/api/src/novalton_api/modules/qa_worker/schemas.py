"""HTTP contracts for one bounded QA Worker validation assignment."""

from pydantic import ConfigDict

from novalton_api.modules.agents.schemas import AgentExecutionResponse
from novalton_api.modules.qa_worker.contracts import QAValidationInput, QAWorkerResult


class QAWorkerValidationRequest(QAValidationInput):
    pass


class QAWorkerValidationResponse(AgentExecutionResponse):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result: QAWorkerResult | None = None
