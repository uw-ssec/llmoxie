from pydantic import BaseModel

class GenerationRequest(BaseModel):
    prompt: str
    generation_model: str
