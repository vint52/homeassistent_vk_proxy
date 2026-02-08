# vk_bot

Small FastAPI service that forwards messages to the VK API.

## Requirements

- Python 3.10+

## Setup

```bash
cd vk_bot
pip install -r requirements.txt
```

Set environment variables (see `.env.example`), or create a local `.env`.
The service loads `.env` automatically on startup.

Additional environment variables:
- `VK_GROUP_ID` - numeric community ID for `/send_post` (without `-`).

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 80
```

You can override the port via the `PORT` environment variable.

## Request

`POST /send_message` with JSON body:

```json
{
  "token": "INTERNAL_TOKEN",
  "message": "Hello from vk_bot"
}
```

Example:

```bash
curl -X POST http://localhost:80/send_message \
  -H "Content-Type: application/json" \
  -d '{"token":"INTERNAL_TOKEN","message":"Hello from vk_bot"}'
```

`POST /send_post` with JSON body:

```json
{
  "token": "INTERNAL_TOKEN",
  "message": "New community post",
  "image": "https://example.com/image.jpg"
}
```

The `image` field is optional. Omit it if you want a text-only post.

Example:

```bash
curl -X POST http://localhost:80/send_post \
  -H "Content-Type: application/json" \
  -d '{"token":"INTERNAL_TOKEN","message":"New community post","image":"https://example.com/image.jpg"}'
```

Note: `/send_post` requires a community access token with the `wall` permission.
If you pass `image`, the token must also include the `photos` permission.

`POST /send_image` with JSON body:

```json
{
  "token": "INTERNAL_TOKEN",
  "image": "https://example.com/image.jpg"
}
```

Example:

```bash
curl -X POST http://localhost:80/send_image \
  -H "Content-Type: application/json" \
  -d '{"token":"INTERNAL_TOKEN","image":"https://example.com/image.jpg"}'
```

`POST /send_video` with JSON body:

```json
{
  "token": "INTERNAL_TOKEN",
  "video": "https://example.com/video.mp4"
}
```

Example:

```bash
curl -X POST http://localhost:80/send_video \
  -H "Content-Type: application/json" \
  -d '{"token":"INTERNAL_TOKEN","video":"https://example.com/video.mp4"}'
```

Note: for group tokens `/send_video` uploads the file as a document, so the
token must include the `docs` permission. If you need a true `video...`
attachment, use a user access token with the `video` permission.
