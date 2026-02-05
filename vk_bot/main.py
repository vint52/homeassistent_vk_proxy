from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from config import ConfigError, Settings, get_settings
from schemas import (
    SendImageRequest,
    SendMessageRequest,
    SendPostRequest,
    SendVideoRequest,
)
from vk_api import (
    VkApiError,
    send_image_url,
    send_message as send_vk_message,
    send_post as send_vk_post,
    send_video_url,
)

app = FastAPI()

@app.exception_handler(ConfigError)
async def config_error_handler(_request: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.post("/send_message")
async def send_message(
    payload: SendMessageRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    if payload.token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        return await send_vk_message(settings, payload.message)
    except VkApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/send_post")
async def send_post(
    payload: SendPostRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    if payload.token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        return await send_vk_post(settings, payload.message)
    except VkApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/send_image")
async def send_image(
    payload: SendImageRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    if payload.token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        return await send_image_url(settings, str(payload.image))
    except VkApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/send_video")
async def send_video(
    payload: SendVideoRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    if payload.token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        return await send_video_url(settings, str(payload.video))
    except VkApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
