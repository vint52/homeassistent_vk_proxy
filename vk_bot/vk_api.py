import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from config import ConfigError, Settings


class VkApiError(RuntimeError):
    pass


def _summarize_response(response: httpx.Response) -> str:
    content_type = response.headers.get("Content-Type", "unknown")
    summary_parts = [f"HTTP {response.status_code}", f"content-type {content_type}"]
    try:
        text = response.text.strip()
    except Exception:
        text = ""
    if text:
        snippet = " ".join(text.split())
        if len(snippet) > 200:
            snippet = f"{snippet[:200]}..."
        summary_parts.append(f"body: {snippet}")
    return ", ".join(summary_parts)


def _method_url(settings: Settings, method: str) -> str:
    base_url = settings.vk_api_url.rsplit("/", 1)[0]
    return f"{base_url}/{method}"


def _raise_if_vk_error(data: Dict[str, Any], method: Optional[str] = None) -> None:
    if "error" in data:
        message = data["error"].get("error_msg", "VK API error")
        if method:
            message = f"{method}: {message}"
        raise VkApiError(message)


def _extract_response(data: Dict[str, Any]) -> Any:
    _raise_if_vk_error(data)
    if "response" not in data:
        raise VkApiError("Invalid response from VK API")
    return data["response"]


def _get_group_id(settings: Settings) -> int:
    group_id = settings.vk_group_id
    if not group_id:
        raise ConfigError("VK_GROUP_ID is not set")
    try:
        return abs(int(group_id.strip()))
    except ValueError as exc:
        raise ConfigError("VK_GROUP_ID must be an integer") from exc


def _get_group_owner_id(settings: Settings) -> int:
    return -_get_group_id(settings)


async def _post_vk_method(
    settings: Settings,
    method: str,
    data: Dict[str, Any],
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    payload = {
        "access_token": settings.vk_access_token,
        "v": settings.vk_api_version,
        **data,
    }

    try:
        response = await client.post(_method_url(settings, method), data=payload)
    except httpx.RequestError as exc:
        raise VkApiError("Failed to reach VK API") from exc

    if response.status_code >= 400:
        raise VkApiError(f"VK API HTTP error ({_summarize_response(response)})")

    try:
        response_data = response.json()
    except ValueError as exc:
        raise VkApiError(
            f"Invalid response from VK API ({_summarize_response(response)})"
        ) from exc

    _raise_if_vk_error(response_data, method)
    return response_data


async def send_message(settings: Settings, message: str) -> Dict[str, Any]:
    data = {
        "peer_id": settings.vk_peer_id,
        "message": message,
        "random_id": 0,
    }

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        return await _post_vk_method(settings, "messages.send", data, client)


async def send_post(
    settings: Settings, message: str, image_url: Optional[str] = None
) -> Dict[str, Any]:
    data = {
        "owner_id": _get_group_owner_id(settings),
        "from_group": 1,
        "message": message,
    }

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        if image_url:
            data["attachments"] = await _upload_wall_photo(settings, image_url, client)
        return await _post_vk_method(settings, "wall.post", data, client)


async def _upload_wall_photo(
    settings: Settings, image_url: str, client: httpx.AsyncClient
) -> str:
    image_bytes, content_type, filename = await _download_image(image_url, client)
    group_id = _get_group_id(settings)

    upload_data = await _post_vk_method(
        settings,
        "photos.getWallUploadServer",
        {"group_id": group_id},
        client,
    )
    upload_info = _extract_response(upload_data)
    upload_url = upload_info.get("upload_url")
    if not upload_url:
        raise VkApiError("Upload URL not received from VK API")

    try:
        upload_response = await client.post(
            upload_url,
            files={
                "photo": (
                    filename,
                    image_bytes,
                    content_type or "application/octet-stream",
                )
            },
        )
    except httpx.RequestError as exc:
        raise VkApiError("Failed to upload image to VK") from exc

    try:
        upload_payload = upload_response.json()
    except ValueError as exc:
        raise VkApiError("Invalid upload response from VK API") from exc

    for key in ("server", "photo", "hash"):
        if key not in upload_payload:
            raise VkApiError("Invalid upload response from VK API")

    save_data = await _post_vk_method(
        settings,
        "photos.saveWallPhoto",
        {
            "group_id": group_id,
            "server": upload_payload["server"],
            "photo": upload_payload["photo"],
            "hash": upload_payload["hash"],
        },
        client,
    )
    save_response = _extract_response(save_data)
    if not save_response:
        raise VkApiError("Image was not saved by VK API")

    photo_info = save_response[0]
    owner_id = photo_info.get("owner_id")
    photo_id = photo_info.get("id")
    if owner_id is None or photo_id is None:
        raise VkApiError("Invalid photo data from VK API")

    access_key = photo_info.get("access_key")
    attachment = f"photo{owner_id}_{photo_id}"
    if access_key:
        attachment = f"{attachment}_{access_key}"
    return attachment


def _filename_from_url(url: str, content_type: Optional[str]) -> str:
    name = Path(urlparse(url).path).name or "image"
    if "." not in name and content_type:
        extension = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if extension:
            name = f"{name}{extension}"
    return name


async def _download_image(
    image_url: str, client: httpx.AsyncClient
) -> Tuple[bytes, Optional[str], str]:
    try:
        response = await client.get(image_url, follow_redirects=True)
    except httpx.RequestError as exc:
        raise VkApiError("Failed to download image") from exc

    if response.status_code >= 400:
        raise VkApiError(
            f"Failed to download image ({_summarize_response(response)})"
        )

    content_type = response.headers.get("Content-Type")
    if content_type and not content_type.lower().startswith("image/"):
        raise VkApiError(
            f"URL does not point to an image (content-type {content_type})"
        )

    content = response.content
    if not content:
        raise VkApiError("Downloaded image is empty")

    filename = _filename_from_url(image_url, content_type)
    return content, content_type, filename


async def _download_video(
    video_url: str, client: httpx.AsyncClient
) -> Tuple[bytes, Optional[str], str]:
    try:
        response = await client.get(video_url, follow_redirects=True)
    except httpx.RequestError as exc:
        raise VkApiError("Failed to download video") from exc

    if response.status_code >= 400:
        raise VkApiError(
            f"Failed to download video ({_summarize_response(response)})"
        )

    content_type = response.headers.get("Content-Type")
    if content_type:
        normalized = content_type.lower()
        if not (
            normalized.startswith("video/")
            or normalized.startswith("application/octet-stream")
        ):
            raise VkApiError(
                f"URL does not point to a video (content-type {content_type})"
            )

    content = response.content
    if not content:
        raise VkApiError("Downloaded video is empty")

    filename = _filename_from_url(video_url, content_type)
    return content, content_type, filename


async def send_image_url(settings: Settings, image_url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        image_bytes, content_type, filename = await _download_image(image_url, client)

        upload_data = await _post_vk_method(
            settings,
            "photos.getMessagesUploadServer",
            {"peer_id": settings.vk_peer_id},
            client,
        )
        upload_info = _extract_response(upload_data)
        upload_url = upload_info.get("upload_url")
        if not upload_url:
            raise VkApiError("Upload URL not received from VK API")

        try:
            upload_response = await client.post(
                upload_url,
                files={
                    "photo": (
                        filename,
                        image_bytes,
                        content_type or "application/octet-stream",
                    )
                },
            )
        except httpx.RequestError as exc:
            raise VkApiError("Failed to upload image to VK") from exc

        try:
            upload_payload = upload_response.json()
        except ValueError as exc:
            raise VkApiError("Invalid upload response from VK API") from exc

        for key in ("server", "photo", "hash"):
            if key not in upload_payload:
                raise VkApiError("Invalid upload response from VK API")

        save_data = await _post_vk_method(
            settings,
            "photos.saveMessagesPhoto",
            {
                "server": upload_payload["server"],
                "photo": upload_payload["photo"],
                "hash": upload_payload["hash"],
            },
            client,
        )
        save_response = _extract_response(save_data)
        if not save_response:
            raise VkApiError("Image was not saved by VK API")

        photo_info = save_response[0]
        owner_id = photo_info.get("owner_id")
        photo_id = photo_info.get("id")
        if owner_id is None or photo_id is None:
            raise VkApiError("Invalid photo data from VK API")

        access_key = photo_info.get("access_key")
        attachment = f"photo{owner_id}_{photo_id}"
        if access_key:
            attachment = f"{attachment}_{access_key}"

        return await _post_vk_method(
            settings,
            "messages.send",
            {
                "peer_id": settings.vk_peer_id,
                "attachment": attachment,
                "random_id": 0,
            },
            client,
        )


async def send_video_url(settings: Settings, video_url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        video_bytes, content_type, filename = await _download_video(video_url, client)

        try:
            return await _send_video_via_save(
                settings, client, video_bytes, content_type, filename
            )
        except VkApiError as exc:
            if "group auth" not in str(exc).lower():
                raise

        return await _send_video_as_document(
            settings, client, video_bytes, content_type, filename
        )


async def _send_video_via_save(
    settings: Settings,
    client: httpx.AsyncClient,
    video_bytes: bytes,
    content_type: Optional[str],
    filename: str,
) -> Dict[str, Any]:
    save_data = await _post_vk_method(
        settings,
        "video.save",
        {
            "name": filename,
            "is_private": 1,
        },
        client,
    )
    save_response = _extract_response(save_data)
    upload_url = save_response.get("upload_url")
    if not upload_url:
        raise VkApiError("Upload URL not received from VK API")

    try:
        upload_response = await client.post(
            upload_url,
            files={
                "video_file": (
                    filename,
                    video_bytes,
                    content_type or "application/octet-stream",
                )
            },
        )
    except httpx.RequestError as exc:
        raise VkApiError("Failed to upload video to VK") from exc

    if upload_response.status_code >= 400:
        raise VkApiError("Failed to upload video to VK")

    owner_id = save_response.get("owner_id")
    video_id = save_response.get("video_id") or save_response.get("vid")
    if owner_id is None or video_id is None:
        raise VkApiError("Invalid video data from VK API")

    access_key = save_response.get("access_key")
    attachment = f"video{owner_id}_{video_id}"
    if access_key:
        attachment = f"{attachment}_{access_key}"

    return await _post_vk_method(
        settings,
        "messages.send",
        {
            "peer_id": settings.vk_peer_id,
            "attachment": attachment,
            "random_id": 0,
        },
        client,
    )


def _extract_doc_info(save_response: Any) -> Dict[str, Any]:
    if isinstance(save_response, dict):
        if "doc" in save_response:
            return save_response["doc"]
        if save_response.get("type") == "doc" and "doc" in save_response:
            return save_response["doc"]
    if isinstance(save_response, list) and save_response:
        return save_response[0]
    raise VkApiError("Invalid document data from VK API")


async def _send_video_as_document(
    settings: Settings,
    client: httpx.AsyncClient,
    video_bytes: bytes,
    content_type: Optional[str],
    filename: str,
) -> Dict[str, Any]:
    upload_data = await _post_vk_method(
        settings,
        "docs.getMessagesUploadServer",
        {"peer_id": settings.vk_peer_id, "type": "doc"},
        client,
    )
    upload_info = _extract_response(upload_data)
    upload_url = upload_info.get("upload_url")
    if not upload_url:
        raise VkApiError("Upload URL not received from VK API")

    try:
        upload_response = await client.post(
            upload_url,
            files={
                "file": (
                    filename,
                    video_bytes,
                    content_type or "application/octet-stream",
                )
            },
        )
    except httpx.RequestError as exc:
        raise VkApiError("Failed to upload video to VK") from exc

    try:
        upload_payload = upload_response.json()
    except ValueError as exc:
        raise VkApiError("Invalid upload response from VK API") from exc

    file_token = upload_payload.get("file")
    if not file_token:
        raise VkApiError("Invalid upload response from VK API")

    save_data = await _post_vk_method(
        settings,
        "docs.save",
        {"file": file_token, "title": filename},
        client,
    )
    save_response = _extract_response(save_data)
    doc_info = _extract_doc_info(save_response)

    owner_id = doc_info.get("owner_id")
    doc_id = doc_info.get("id") or doc_info.get("doc_id")
    if owner_id is None or doc_id is None:
        raise VkApiError("Invalid document data from VK API")

    access_key = doc_info.get("access_key")
    attachment = f"doc{owner_id}_{doc_id}"
    if access_key:
        attachment = f"{attachment}_{access_key}"

    return await _post_vk_method(
        settings,
        "messages.send",
        {
            "peer_id": settings.vk_peer_id,
            "attachment": attachment,
            "random_id": 0,
        },
        client,
    )
