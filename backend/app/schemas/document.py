from pydantic import BaseModel
from datetime import datetime

class DocumentOut(BaseModel):
    id: int
    filename: str
    created_at: datetime

    class Config:
        from_attributes = True
