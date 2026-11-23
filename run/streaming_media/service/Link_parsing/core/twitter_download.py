"""Temporary import-compatible Twitter media placeholders; no downloads are performed."""


def is_twitter_gif(url: str) -> bool:
    """Skip Twitter GIF detection until the real implementation is restored."""
    return False


def twitter_gif_reference(url: str) -> str:
    """Return the URL unchanged while GIF handling is unavailable."""
    return url


async def download_twitter_media(
    url: str, filepath: str, proxy: str = None, media_type: str = None
) -> str:
    """Keep the async download interface available for existing imports."""
    raise NotImplementedError("Twitter media download is temporarily unavailable.")
