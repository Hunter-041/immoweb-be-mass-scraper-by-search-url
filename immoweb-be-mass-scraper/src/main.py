import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure local packages are importable when running as a script
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from scraper.crawler import ImmowebCrawler
from monitoring.delta_mode import annotate_with_delta, summarize_delta
from outputs.exporter_json import export_json
from outputs.exporter_csv import export_csv
from outputs.exporter_excel import export_excel
from scraper.utils import get_logger

ROOT_DIR = CURRENT_DIR.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = CURRENT_DIR / "config"

def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def apply_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(config)
    cfg.setdefault("max_pages_to_scrape", 3)
    cfg.setdefault("concurrency", 5)
    cfg.setdefault("request_timeout", 30)
    cfg.setdefault("request_delay", 0.5)
    cfg.setdefault("user_agent", "ImmowebMassScraper/1.0 (+https://bitbash.dev)")
    cfg.setdefault("output_formats", ["json", "csv", "excel"])
    cfg.setdefault("delta_mode_enabled", True)
    return cfg

def load_urls(urls_file: Path) -> List[str]:
    if not urls_file.exists():
        raise FileNotFoundError(f"URLs file not found: {urls_file}")
    urls: List[str] = []
    with urls_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    if not urls:
        raise ValueError(f"No URLs found in {urls_file}")
    return urls

def load_previous_snapshot(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except json.JSONDecodeError:
        return []

async def run_scraper(
    config: Dict[str, Any],
    urls_file: Path,
    output_prefix: Path,
    delta_mode_enabled: bool,
    logger: logging.Logger,
) -> None:
    urls = load_urls(urls_file)
    logger.info("Loaded %d search URL(s) from %s", len(urls), urls_file)

    crawler = ImmowebCrawler(
        max_pages=config["max_pages_to_scrape"],
        concurrency=config["concurrency"],
        request_timeout=config["request_timeout"],
        request_delay=config["request_delay"],
        user_agent=config["user_agent"],
        logger=logger,
    )

    listings = await crawler.crawl_search_urls(urls)
    logger.info("Collected %d listing(s) before delta processing", len(listings))

    json_path = output_prefix.with_suffix(".json")
    csv_path = output_prefix.with_suffix(".csv")
    xlsx_path = output_prefix.with_suffix(".xlsx")

    previous: List[Dict[str, Any]] = []
    annotated: List[Dict[str, Any]] = listings

    if delta_mode_enabled:
        previous = load_previous_snapshot(json_path)
        annotated = annotate_with_delta(previous, listings)
        summary = summarize_delta(annotated)
        logger.info(
            "Delta summary — total: %(total)d, new: %(new)d, delisted: %(delisted)d, active: %(active)d",
            summary,
        )
    else:
        logger.info("Delta mode disabled; skipping delta annotation")

    output_formats: List[str] = config["output_formats"]

    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    if "json" in output_formats:
        export_json(annotated, json_path)
        logger.info("Saved JSON output to %s", json_path)

    if "csv" in output_formats:
        export_csv(annotated, csv_path)
        logger.info("Saved CSV output to %s", csv_path)

    if "excel" in output_formats:
        export_excel(annotated, xlsx_path)
        logger.info("Saved Excel output to %s", xlsx_path)

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Immoweb.be Mass Scraper (by search URL)"
    )
    default_config_path = CONFIG_DIR / "settings.example.json"
    default_urls_path = DATA_DIR / "sample_input_urls.txt"
    default_output_prefix = DATA_DIR / "output_sample"

    parser.add_argument(
        "--config",
        type=str,
        default=str(default_config_path),
        help=f"Path to JSON settings file (default: {default_config_path})",
    )
    parser.add_argument(
        "--urls-file",
        type=str,
        default=str(default_urls_path),
        help=f"Path to text file with search URLs (default: {default_urls_path})",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=str(default_output_prefix),
        help=f"Path prefix for outputs without extension (default: {default_output_prefix})",
    )
    parser.add_argument(
        "--no-delta",
        action="store_true",
        help="Disable delta mode (do not compute new/delisted listings)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser

def configure_logging(level: str) -> logging.Logger:
    logger = get_logger("immoweb_scraper")
    lvl = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(lvl)
    return logger

async def async_main(cli_args: Optional[List[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(cli_args)

    logger = configure_logging(args.log_level)

    config_path = Path(args.config)
    raw_config = load_config(config_path)
    config = apply_defaults(raw_config)

    urls_file = Path(args.urls_file)
    output_prefix = Path(args.output_prefix)
    delta_mode_enabled = config["delta_mode_enabled"] and not args.no_delta

    logger.info("Starting Immoweb scraper")
    logger.debug("Using configuration: %s", json.dumps(config, indent=2))

    try:
        await run_scraper(
            config=config,
            urls_file=urls_file,
            output_prefix=output_prefix,
            delta_mode_enabled=delta_mode_enabled,
            logger=logger,
        )
    except Exception as exc:
        logger.exception("Unexpected error during scraping: %s", exc)
        raise

if __name__ == "__main__":
    asyncio.run(async_main())