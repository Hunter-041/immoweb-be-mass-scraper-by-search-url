import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    return logger

async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout: int,
    logger: logging.Logger,
    max_retries: int = 3,
    backoff_factor: float = 1.5,
) -> Optional[str]:
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.warning(
                        "Non-200 status %s for %s (attempt %s)",
                        resp.status,
                        url,
                        attempt,
                    )
                return text
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(
                "Request error for %s on attempt %s/%s: %s",
                url,
                attempt,
                max_retries,
                e,
            )
            if attempt == max_retries:
                logger.error("Giving up on %s after %s attempts", url, max_retries)
                return None
            await asyncio.sleep(backoff_factor ** (attempt - 1))
    return None

def build_paged_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)

def extract_listing_id_from_url(url: str) -> Optional[str]:
    """
    Extract a numeric listing ID from an Immoweb URL if present.
    """
    path_parts = urlparse(url).path.split("/")
    for part in reversed(path_parts):
        if part.isdigit():
            return part
    return None