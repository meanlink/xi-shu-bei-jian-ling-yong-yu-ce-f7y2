from pydantic import BaseModel, Field
class QuarantineInput(BaseModel):
    dataset_id: int
    reason: str = Field(min_length=5, max_length=500)
class ReplacementInput(BaseModel):
    dataset_id: int
