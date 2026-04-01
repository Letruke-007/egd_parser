from pydantic import BaseModel


class ParseRequest(BaseModel):
    filename: str
