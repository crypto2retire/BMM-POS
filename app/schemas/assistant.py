from pydantic import BaseModel
from typing import Optional


class AssistantChatRequest(BaseModel):
    message: str
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    form_context: Optional[str] = None
    last_item_id: Optional[int] = None


class AssistantChatResponse(BaseModel):
    reply: str
    action_taken: Optional[str] = None
    item_id: Optional[int] = None
