from typing import Optional

from pydantic import BaseModel, HttpUrl


class SendMessageRequest(BaseModel):
    token: str
    message: str


class SendImageRequest(BaseModel):
    token: str
    image: HttpUrl


class SendVideoRequest(BaseModel):
    token: str
    video: HttpUrl


class SendPostRequest(BaseModel):
    token: str
    message: str
    image: Optional[HttpUrl] = None
