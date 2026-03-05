from pydantic import BaseModel


class UndoResponse(BaseModel):
    status: str
    message: str
