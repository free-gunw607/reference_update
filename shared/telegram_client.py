from telethon import TelegramClient
from telethon.sessions import StringSession

_client = None


def get_client(cfg) -> TelegramClient:
    global _client
    if _client and _client.is_connected():
        return _client
    _client = TelegramClient(
        StringSession(cfg.session_string),
        cfg.api_id,
        cfg.api_hash,
    )
    return _client


async def ensure_connected(cfg) -> TelegramClient:
    client = get_client(cfg)
    if not client.is_connected():
        await client.start()
    return client


async def disconnect_all():
    global _client
    if _client and _client.is_connected():
        await _client.disconnect()
    _client = None
