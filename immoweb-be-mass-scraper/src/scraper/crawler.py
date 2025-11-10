import asyncio
import logging
from typing import List, Dict, Any, Optional

import aiohttp

from .parser import extract_listings_from_search_page
from .utils import fetch, build_paged_url, get_logger

class ImmowebCrawler:
    def __init__(
        self,
        *,
        max_pages: int = 3,
        concurrency: int = 5,
        request_timeout: int = 30,
        request_delay: float = 0.5,
        user_agent: str = "ImmowebMassScraper/1.0",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.max_pages = max_pages
        self.concurrency = concurrency
        self.request_timeout = request_timeout
        self.request_delay = request_delay
        self.user_agent = user_agent
        self.logger = logger or get_logger(self.__class__.__name__)

    async def crawl_search_urls(self, urls: List[str]) -> List[Dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.concurrency)
        listings: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession(
            headers={"User-Agent": self.user_agent}
        ) as session:
            tasks = [
                self._crawl_single_search(
                    session=session,
                    base_url=url.strip(),
                    semaphore=semaphore,
                )
                for url in urls
            ]
            for coro in asyncio.as_completed(tasks):
                result = await coro
                listings.extend(result)

        # Deduplicate by id or url
        seen_ids = set()
        seen_urls = set()
        deduped: List[Dict[str, Any]] = []
        for item in listings:
            ident = item.get("id")
            url = item.get("url")
            key = ident or url
            if not key:
                deduped.append(item)
                continue
            if ident and ident in seen_ids:
                continue
            if url and url in seen_urls:
                continue
            if ident:
                seen_ids.add(ident)
            if url:
                seen_urls.add(url)
            deduped.append(item)

        self.logger.info("After deduplication: %d listing(s)", len(deduped))
        return deduped

    async def _crawl_single_search(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        semaphore: asyncio.Semaphore,
    ) -> List[Dict[str, Any]]:
        listings: List[Dict[str, Any]] = []
        self.logger.info("Crawling search URL: %s", base_url)

        for page in range(1, self.max_pages + 1):
            page_url = build_paged_url(base_url, page)
            async with semaphore:
                html = await fetch(
                    session,
                    page_url,
                    timeout=self.request_timeout,
                    logger=self.logger,
                )
            if not html:
                self.logger.warning(
                    "Empty response for %s; stopping pagination for this search URL",
                    page_url,
                )
                break

            page_listings = extract_listings_from_search_page(html, search_url=base_url)
            self.logger.info(
                "Page %s for %s returned %d listing(s)",
                page,
                base_url,
                len(page_listings),
            )

            if not page_listings:
                # Assume we've reached the end of results
                break

            listings.extend(page_listings)

            # Polite delay between page requests to the same search
            await asyncio.sleep(self.request_delay)

        return listings