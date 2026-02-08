# VK Proxy

Сервис-прокси для отправки в ВК сообщений, фото и видео (а также постов на
стену сообщества) по HTTP.

## Пример .env

Файл `.env` должен лежать в корне проекта (его читает `docker-compose.yml`).
За основу возьмите `.env.example`.

```
INTERNAL_TOKEN=change-me
HOST_PORT=81
VK_ACCESS_TOKEN=vk-access-token
VK_PEER_ID=123456789
VK_GROUP_ID=123456789
VK_API_VERSION=5.131
VK_REQUEST_TIMEOUT=30
```

## Настройка ВК

### 1. Создать сообщество

- Перейдите в раздел "Сообщества" и нажмите "Создать сообщество"
  (`https://vk.com/groups?tab=admin`).
- Выберите тип (группа или публичная страница) и завершите создание.

### 2. Включить сообщения сообщества

- Откройте настройки сообщества.
- В разделе "Сообщения" включите "Сообщения сообщества".

### 3. Получить API токен

- В настройках сообщества откройте "Работа с API" -> "Ключи доступа".
- Нажмите "Создать ключ" и выдайте права:
  - "Сообщения сообщества" (обязательно для `messages.send`).
  - "Фотографии", "Видео", "Документы" (для отправки медиа).
  - "Стена" (если используете `/send_post`).
- Скопируйте полученный ключ в `VK_ACCESS_TOKEN`.

### 4. Узнать ID сообщества (VK_GROUP_ID)

- Если адрес сообщества выглядит как `vk.com/club123` или `vk.com/public123`,
  число в адресе и есть ID.
- Если задан короткий адрес, откройте "Основная информация" в настройках
  сообщества или воспользуйтесь `https://vk.com/dev/groups.getById`, чтобы
  получить числовой ID.

### 5. Узнать peer_id (VK_PEER_ID)

- Для личного сообщения используйте ID пользователя.
  - Если профиль вида `vk.com/id123`, то `123` и есть нужное значение.
  - При коротком адресе можно получить ID через
    `https://vk.com/dev/users.get`.
- Для беседы: откройте чат в веб-версии VK, в адресной строке будет
  `im?sel=c123`, где `123` — chat_id. Тогда
  `peer_id = 2000000000 + chat_id`.

## Что означают переменные в .env

- `INTERNAL_TOKEN` — секретный токен, который должен передаваться в поле
  `token` во всех HTTP-запросах к этому сервису.
- `HOST_PORT` — внешний порт, на котором доступен сервис (по умолчанию `81`).
- `VK_ACCESS_TOKEN` — токен доступа сообщества, созданный в "Работе с API".
- `VK_PEER_ID` — получатель сообщений: ID пользователя или peer_id беседы.
- `VK_GROUP_ID` — числовой ID сообщества; нужен для публикации постов на стене.
- `VK_API_VERSION` — версия VK API (по умолчанию используется `5.131`).
- `VK_REQUEST_TIMEOUT` — таймаут запросов к VK API в секундах (по умолчанию `30`).

## Home Assistant

### configuration.yaml

Добавьте блок `rest_command` и подставьте свой `INTERNAL_TOKEN`.
`<VK_PROXY_HOST:PORT>` — адрес созданного сервиса-прокси:

```
rest_command:
  vk_send_message:
    url: "http://<VK_PROXY_HOST:PORT>/send_message"
    method: POST
    content_type: "application/json"
    payload: >
      {"token":"<INTERNAL_TOKEN>","message": {{ message | tojson }} }

  vk_send_image:
    url: "http://<VK_PROXY_HOST:PORT>/send_image"
    method: POST
    content_type: "application/json"
    payload: >
      {"token":"<INTERNAL_TOKEN>","image": {{ image | tojson }} }

  vk_send_video:
    url: "http://<VK_PROXY_HOST:PORT>/send_video"
    method: POST
    content_type: "application/json"
    payload: >
      {"token":"<INTERNAL_TOKEN>","video": {{ video | tojson }} }

  vk_send_post:
    url: "http://<VK_PROXY_HOST:PORT>/send_post"
    method: POST
    content_type: "application/json"
    payload: >
      {"token":"<INTERNAL_TOKEN>","message": {{ message | tojson }} }
```

### Как вызывать

`http://<FRIGATE_HOST:PORT>` — адрес сервера Frigate:

```
service: rest_command.vk_send_message
data:
  message: 'Тест "кавычки" и новая строка
  ок'

service: rest_command.vk_send_image
data:
  image: "http://<FRIGATE_HOST:PORT>/api/events/ID/snapshot.jpg?bbox=1&crop=0"  # адрес сервиса Frigate

service: rest_command.vk_send_video
data:
  video: "http://<FRIGATE_HOST:PORT>/api/events/ID/clip.mp4"  # адрес сервиса Frigate
```

## Troubleshooting

- `502 Bad Gateway` means the proxy hit an error; check the JSON body for details.
  - `wget --content-on-error -O - ...`
  - `curl -sS -D - -o - ...`
- Make sure the media URL is reachable from the proxy container and returns a
  `video/*` or `image/*` content-type.
- For long downloads, increase `VK_REQUEST_TIMEOUT` in `.env`.
