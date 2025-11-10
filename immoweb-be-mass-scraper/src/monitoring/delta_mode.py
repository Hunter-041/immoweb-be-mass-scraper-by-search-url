from typing import List, Dict, Any, Tuple, Optional

def _build_index(
    items: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for item in items:
        ident = item.get("id") or item.get("url")
        if not ident:
            # Skip items that cannot be reliably identified between runs
            continue
        index[str(ident)] = item
    return index

def annotate_with_delta(
    previous: List[Dict[str, Any]],
    current: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compare previous and current listing snapshots and annotate each listing with
    `apify_monitoring_status`:

    - "new": listing present now but not in previous snapshot
    - "active": listing present in both snapshots
    - "delisted": listing present before but missing now

    Delisted items are appended to the output so a consumer can react to them
    even though they no longer appear in the current crawl.
    """
    prev_index = _build_index(previous)
    curr_index = _build_index(current)

    annotated: List[Dict[str, Any]] = []

    # First, annotate current listings as new or active
    for item in current:
        ident = item.get("id") or item.get("url")
        status = "unknown"
        if ident:
            key = str(ident)
            if key in prev_index:
                status = "active"
            else:
                status = "new"
        updated = dict(item)
        updated["apify_monitoring_status"] = status
        annotated.append(updated)

    # Then, add delisted items based on previous snapshot
    for ident, prev_item in prev_index.items():
        if ident not in curr_index:
            delisted = dict(prev_item)
            delisted["apify_monitoring_status"] = "delisted"
            annotated.append(delisted)

    return annotated

def summarize_delta(
    annotated_listings: List[Dict[str, Any]]
) -> Dict[str, int]:
    total = len(annotated_listings)
    new = sum(1 for it in annotated_listings if it.get("apify_monitoring_status") == "new")
    delisted = sum(
        1 for it in annotated_listings if it.get("apify_monitoring_status") == "delisted"
    )
    active = sum(
        1 for it in annotated_listings if it.get("apify_monitoring_status") == "active"
    )
    return {
        "total": total,
        "new": new,
        "delisted": delisted,
        "active": active,
    }