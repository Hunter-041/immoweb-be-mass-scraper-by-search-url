from pathlib import Path
from typing import List, Dict, Any

import pandas as pd

def export_excel(listings: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not listings:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(listings)
    df.to_excel(path, index=False)