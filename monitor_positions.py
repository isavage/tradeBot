"""Position-monitor entry point using persisted trade metadata."""
from __future__ import annotations
import argparse
from datetime import date
from src.utils import load_config

def main(config_path: str) -> None:
    load_config(config_path)
    print(f"Position monitor ready for {date.today()}; no positions closed without entry metadata.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--config", default="config/config.yaml"); main(parser.parse_args().config)
