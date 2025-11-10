import csv
from pathlib import Path
from typing import List, Dict, Any

def export_csv(listings: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not listings:
        # Create an empty file with just a header row for visibility
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["no_data"])
        return

    # Collect all keys across items for a stable header
    fieldnames = set()
    for item in listings:
        fieldnames.update(item.keys())
    ordered_fieldnames = sorted(fieldnames)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_fieldnames)
        writer.writeheader()
        for item in listings:
            writer.writerow(item)