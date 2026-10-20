"""Bounded trusted-operator enqueue input; never registered as a model tool."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    workflow_run_id: UUID
    request_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    priority: int = Field(default=0, ge=-100, le=100)
    eligible_at: AwareDatetime | None = None
    deadline: AwareDatetime
    max_attempts: int = Field(default=8, ge=0, le=64)
    max_model_calls: int = Field(default=24, ge=0, le=128)
    allow_unknown_cost: bool = False
    dependencies: tuple[UUID, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_dependencies(self) -> "DispatchRequest":
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("duplicate dependency")
        if self.eligible_at is not None and self.eligible_at > self.deadline:
            raise ValueError("eligibility exceeds deadline")
        return self
