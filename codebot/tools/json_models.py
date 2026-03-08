from pydantic import BaseModel, ConfigDict
from inflection import camelize

class CamelcaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda x: camelize(x, False),
        populate_by_name=True,
        from_attributes=True,
    )

class ClaudeAuthResponse(CamelcaseModel):
    logged_in: bool
    email: str | None = None
    auth_method: str
    org_id: str | None = None
    org_name: str | None = None
    subscription_type: str | None = None