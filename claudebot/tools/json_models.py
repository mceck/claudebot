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
    email: str
    auth_method: str
    org_id: str
    org_name: str | None = None
    subscription_type: str