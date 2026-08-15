"""Configuration, logging, and Alpaca client helpers."""
from __future__ import annotations
import logging
from pathlib import Path
import yaml
from dotenv import load_dotenv

def load_config(path: str | Path) -> dict:
    load_dotenv()
    with Path(path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}

def setup_logging(log_path: str = "trade_bot.log") -> None:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(log_path), logging.StreamHandler()])
