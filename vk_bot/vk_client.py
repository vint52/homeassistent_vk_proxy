import io
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from vk_api import VkApi
from vk_api.exceptions import ApiError, ApiHttpError, VkApiError as VkLibraryError
from vk_api.upload import VkUpload

from config import ConfigError, Settings


class VkApiError(RuntimeError):
    pass


def _summarize_response(response: requests.Response) -> str:
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


def _apply_timeout(session: requests.Session, timeout: float) -> None:
    original_request = session.request

    def request_with_timeout(*args: Any, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", timeout)
        return original_request(*args, **kwargs)

    session.request = request_with_timeout  # type: ignore[assignment]


def _vk_session(settings: Settings, access_token: str) -> VkApi:
    session = VkApi(token=access_token, api_version=settings.vk_api_version)
    _apply_timeout(session.http, settings.request_timeout)
    return session


def _vk_upload(settings: Settings, session: VkApi) -> VkUpload:
    upload = VkUpload(session)
    _apply_timeout(upload.http, settings.request_timeout)
    return upload


def _vk_error_message(exc: Exception) -> str:
    if isinstance(exc, ApiError):
        return exc.error.get("error_msg", str(exc))
    if isinstance(exc, ApiHttpError):
        return str(exc)
    return str(exc)


def _raise_vk_error(exc: Exception, context: Optional[str] = None) -> None:
    message = _vk_error_message(exc)
    if context:
        message = f"{context}: {message}"
    raise VkApiError(message) from exc


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


def _filename_from_url(url: str, content_type: Optional[str]) -> str:
    name = Path(urlparse(url).path).name or "image"
    if "." not in name and content_type:
        extension = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if extension:
            name = f"{name}{extension}"
    return name


def _file_from_bytes(content: bytes, filename: str) -> io.BytesIO:
    buffer = io.BytesIO(content)
    buffer.name = filename
    buffer.seek(0)
    return buffer


def _download_image(image_url: str, timeout: float) -> Tuple[bytes, Optional[str], str]:
    try:
        response = requests.get(image_url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise VkApiError("Failed to download image") from exc

    if response.status_code >= 400:
        raise VkApiError(f"Failed to download image ({_summarize_response(response)})")

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


def _download_video(video_url: str, timeout: float) -> Tuple[bytes, Optional[str], str]:
    try:
        response = requests.get(video_url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise VkApiError("Failed to download video") from exc

    if response.status_code >= 400:
        raise VkApiError(f"Failed to download video ({_summarize_response(response)})")

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


def _build_attachment(
    prefix: str, owner_id: Any, item_id: Any, access_key: Optional[str]
) -> str:
    attachment = f"{prefix}{owner_id}_{item_id}"
    if access_key:
        attachment = f"{attachment}_{access_key}"
    return attachment


def _extract_doc_info(save_response: Any) -> Dict[str, Any]:
    if isinstance(save_response, dict):
        if "doc" in save_response:
            return save_response["doc"]
        if save_response.get("type") == "doc" and "doc" in save_response:
            return save_response["doc"]
    if isinstance(save_response, list) and save_response:
        return save_response[0]
    raise VkApiError("Invalid document data from VK API")


def _photo_attachment(photo_info: Dict[str, Any]) -> str:
    owner_id = photo_info.get("owner_id")
    photo_id = photo_info.get("id") or photo_info.get("photo_id")
    if owner_id is None or photo_id is None:
        raise VkApiError("Invalid photo data from VK API")
    return _build_attachment("photo", owner_id, photo_id, photo_info.get("access_key"))


def _send_message(
    settings: Settings, vk_session: VkApi, attachment: Optional[str] = None, message: str = ""
) -> Dict[str, Any]:
    vk = vk_session.get_api()
    payload: Dict[str, Any] = {
        "peer_id": settings.vk_peer_id,
        "random_id": 0,
    }
    if message:
        payload["message"] = message
    if attachment:
        payload["attachment"] = attachment

    try:
        response = vk.messages.send(**payload)
    except (VkLibraryError, requests.RequestException) as exc:
        _raise_vk_error(exc, "messages.send")
    return {"response": response}


def send_message(settings: Settings, message: str) -> Dict[str, Any]:
    vk_session = _vk_session(settings, settings.vk_access_token)
    return _send_message(settings, vk_session, message=message)


def send_post(
    settings: Settings, message: str, image_url: Optional[str] = None
) -> Dict[str, Any]:
    if image_url and not settings.vk_wall_access_token:
        raise VkApiError(
            "VK_WALL_ACCESS_TOKEN is required for wall images; group tokens "
            "cannot upload photos. Use a user token with wall/photos/offline."
        )
    access_token = settings.vk_wall_access_token or settings.vk_access_token
    vk_session = _vk_session(settings, access_token)
    vk = vk_session.get_api()

    data: Dict[str, Any] = {
        "owner_id": _get_group_owner_id(settings),
        "from_group": 1,
        "message": message,
    }

    if image_url:
        data["attachments"] = _upload_wall_photo(settings, image_url, vk_session)

    try:
        response = vk.wall.post(**data)
    except (VkLibraryError, requests.RequestException) as exc:
        _raise_vk_error(exc, "wall.post")
    return {"response": response}


def _upload_wall_photo(settings: Settings, image_url: str, vk_session: VkApi) -> str:
    image_bytes, _content_type, filename = _download_image(
        image_url, settings.request_timeout
    )
    upload = _vk_upload(settings, vk_session)
    file_obj = _file_from_bytes(image_bytes, filename)

    try:
        photos = upload.photo_wall(file_obj, group_id=_get_group_id(settings))
    except (VkLibraryError, requests.RequestException) as exc:
        if isinstance(exc, ApiError):
            message = exc.error.get("error_msg", "")
            if "Group authorization failed" in message:
                raise VkApiError(
                    "VK_WALL_ACCESS_TOKEN must be a user token (wall/photos/offline). "
                    "Restart the service after updating .env and make sure no "
                    "exported VK_WALL_ACCESS_TOKEN overrides it."
                ) from exc
        _raise_vk_error(exc, "photos.getWallUploadServer")

    if not photos:
        raise VkApiError("Image was not saved by VK API")

    photo_info = photos[0] if isinstance(photos, list) else photos
    return _photo_attachment(photo_info)


def send_image_url(settings: Settings, image_url: str) -> Dict[str, Any]:
    vk_session = _vk_session(settings, settings.vk_access_token)
    upload = _vk_upload(settings, vk_session)
    image_bytes, _content_type, filename = _download_image(
        image_url, settings.request_timeout
    )
    file_obj = _file_from_bytes(image_bytes, filename)

    try:
        photos = upload.photo_messages(file_obj, peer_id=settings.vk_peer_id)
    except (VkLibraryError, requests.RequestException) as exc:
        _raise_vk_error(exc, "photos.getMessagesUploadServer")

    if not photos:
        raise VkApiError("Image was not saved by VK API")

    photo_info = photos[0] if isinstance(photos, list) else photos
    attachment = _photo_attachment(photo_info)
    return _send_message(settings, vk_session, attachment=attachment)


def send_video_url(
    settings: Settings, video_url: str, send_type: str = "video"
) -> Dict[str, Any]:
    video_bytes, _content_type, filename = _download_video(
        video_url, settings.request_timeout
    )

    if send_type == "document":
        vk_session = _vk_session(settings, settings.vk_access_token)
        return _send_video_as_document(settings, vk_session, video_bytes, filename)

    if settings.vk_wall_access_token:
        upload_session = _vk_session(settings, settings.vk_wall_access_token)
        attachment = _save_video_attachment(
            settings, upload_session, video_bytes, filename
        )
        send_session = _vk_session(settings, settings.vk_access_token)
        return _send_message(settings, send_session, attachment=attachment)

    vk_session = _vk_session(settings, settings.vk_access_token)
    try:
        return _send_video_via_save(settings, vk_session, video_bytes, filename)
    except VkApiError as exc:
        if "group authorization failed" not in str(exc).lower():
            raise

    return _send_video_as_document(settings, vk_session, video_bytes, filename)


def _send_video_via_save(
    settings: Settings,
    vk_session: VkApi,
    video_bytes: bytes,
    filename: str,
) -> Dict[str, Any]:
    attachment = _save_video_attachment(settings, vk_session, video_bytes, filename)
    return _send_message(settings, vk_session, attachment=attachment)


def _save_video_attachment(
    settings: Settings,
    vk_session: VkApi,
    video_bytes: bytes,
    filename: str,
) -> str:
    upload = _vk_upload(settings, vk_session)
    file_obj = _file_from_bytes(video_bytes, filename)

    try:
        save_response = upload.video(video_file=file_obj, name=filename, is_private=1)
    except (VkLibraryError, requests.RequestException, ValueError) as exc:
        _raise_vk_error(exc, "video.save")

    owner_id = save_response.get("owner_id")
    video_id = (
        save_response.get("video_id")
        or save_response.get("vid")
        or save_response.get("id")
    )
    if owner_id is None or video_id is None:
        raise VkApiError("Invalid video data from VK API")

    return _build_attachment(
        "video", owner_id, video_id, save_response.get("access_key")
    )


def _send_video_as_document(
    settings: Settings,
    vk_session: VkApi,
    video_bytes: bytes,
    filename: str,
) -> Dict[str, Any]:
    upload = _vk_upload(settings, vk_session)
    file_obj = _file_from_bytes(video_bytes, filename)

    try:
        save_response = upload.document(
            doc=file_obj,
            title=filename,
            message_peer_id=settings.vk_peer_id,
            doc_type="doc",
        )
    except (VkLibraryError, requests.RequestException) as exc:
        _raise_vk_error(exc, "docs.save")

    doc_info = _extract_doc_info(save_response)
    owner_id = doc_info.get("owner_id")
    doc_id = doc_info.get("id") or doc_info.get("doc_id")
    if owner_id is None or doc_id is None:
        raise VkApiError("Invalid document data from VK API")

    attachment = _build_attachment("doc", owner_id, doc_id, doc_info.get("access_key"))
    return _send_message(settings, vk_session, attachment=attachment)
