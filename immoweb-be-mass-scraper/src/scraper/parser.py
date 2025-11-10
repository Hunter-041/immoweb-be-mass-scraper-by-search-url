from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .utils import extract_listing_id_from_url

IMMOWEB_BASE_URL = "https://www.immoweb.be"

def _get_text_or_none(element) -> Optional[str]:
    if not element:
        return None
    text = element.get_text(strip=True)
    return text or None

def _find_price(card) -> Optional[str]:
    for cls in ["price", "result-xl-price", "classified__price"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _get_text_or_none(el)
    # Fallback: any element that looks like a price
    candidates = card.find_all(text=True)
    for text in candidates:
        t = text.strip()
        if t.startswith("€") or "EUR" in t:
            return t
    return None

def _find_location(card) -> Optional[str]:
    for cls in ["locality", "result-xl-locality", "classified__information--address"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _get_text_or_none(el)
    # Fallback
    small = card.find("small")
    return _get_text_or_none(small)

def _find_link(card) -> Optional[str]:
    # Prefer main anchors that point to classified pages
    for a in card.find_all("a", href=True):
        href = a["href"]
        if "/en/classified" in href or "/fr/classified" in href or "/nl/classified" in href:
            return href
    # Fallback: first anchor
    a = card.find("a", href=True)
    if a:
        return a["href"]
    return None

def _find_photos(card) -> List[str]:
    photos: List[str] = []
    for img in card.find_all("img"):
        src = img.get("data-src") or img.get("src")
        if not src:
            continue
        if src.startswith("data:"):
            continue
        photos.append(src)
    # Deduplicate while preserving order
    seen = set()
    unique_photos: List[str] = []
    for p in photos:
        if p not in seen:
            seen.add(p)
            unique_photos.append(p)
    return unique_photos

def _find_property_type(card) -> Optional[str]:
    # Immoweb often shows type in a badge or meta section
    for cls in ["property-type", "result-xl-property-type", "classified__type"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _get_text_or_none(el)
    # Fallback: look for "Apartment", "House", etc. in the card
    text = card.get_text(" ", strip=True)
    for word in ["Apartment", "House", "Studio", "Villa", "Loft"]:
        if word.lower() in text.lower():
            return word
    return None

def _extract_int_from_text(source: Optional[str]) -> Optional[int]:
    if not source:
        return None
    digits = "".join(ch if ch.isdigit() else " " for ch in source)
    parts = [p for p in digits.split() if p]
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None

def _find_bedrooms(card) -> Optional[int]:
    # Common icons or labels
    for cls in ["bedrooms", "bedroom-count"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _extract_int_from_text(el.get_text())
    text = card.get_text(" ", strip=True)
    for label in ["bedroom", "bedrooms", "chambre", "chambres", "slaapkamer", "slaapkamers"]:
        idx = text.lower().find(label)
        if idx != -1:
            snippet = text[max(0, idx - 6) : idx]
            val = _extract_int_from_text(snippet)
            if val is not None:
                return val
    return None

def _find_bathrooms(card) -> Optional[int]:
    for cls in ["bathrooms", "bathroom-count"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _extract_int_from_text(el.get_text())
    text = card.get_text(" ", strip=True)
    for label in ["bathroom", "bathrooms", "sdb", "salle de bain", "badkamer", "badkamers"]:
        idx = text.lower().find(label)
        if idx != -1:
            snippet = text[max(0, idx - 6) : idx]
            val = _extract_int_from_text(snippet)
            if val is not None:
                return val
    return None

def _find_area(card) -> Optional[int]:
    text = card.get_text(" ", strip=True)
    # Look for something like "120 m²"
    for marker in ["m²", "m2"]:
        idx = text.find(marker)
        if idx != -1:
            snippet = text[max(0, idx - 8) : idx]
            val = _extract_int_from_text(snippet)
            if val is not None:
                return val
    return None

def _find_energy_class(card) -> Optional[str]:
    for cls in ["epc", "energy-class"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            txt = _get_text_or_none(el)
            if txt:
                return txt
    # Fallback: search for "PEB" or "EPC" and a grade
    text = card.get_text(" ", strip=True)
    for label in ["PEB", "EPC"]:
        idx = text.upper().find(label)
        if idx != -1 and idx + 4 < len(text):
            snippet = text[idx : idx + 8]
            for grade in ["A", "B", "C", "D", "E", "F", "G"]:
                if grade in snippet:
                    return f"{label} {grade}"
    return None

def _find_publisher(card) -> Optional[str]:
    for cls in ["agency-name", "publisher", "classified__information--agency"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _get_text_or_none(el)
    return None

def _find_contact(card) -> Optional[str]:
    # Often contact details are not fully present on listing cards; try to pick any obvious phone fragment
    text = card.get_text(" ", strip=True)
    digits = "".join(ch if ch.isdigit() or ch in "+ -" else " " for ch in text)
    parts = [p for p in digits.split() if len(p.replace("+", "").replace("-", "")) >= 8]
    if parts:
        return parts[0]
    return None

def _find_date_posted(card) -> Optional[str]:
    for cls in ["date", "posted-date", "classified__publish-date"]:
        el = card.find(class_=lambda c: c and cls in c.split())
        if el:
            return _get_text_or_none(el)
    return None

def extract_listings_from_search_page(
    html: str, search_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Attempt to extract listing data from an Immoweb search results HTML page.

    The parser is intentionally defensive: when a field cannot be extracted,
    it falls back to None instead of raising.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: List[Dict[str, Any]] = []

    # Try a few generic selectors that typically match listing cards
    cards = soup.select("article, .search-result, .result-xl")
    if not cards:
        # fallback: any element with a data-id attribute
        cards = soup.select("[data-id]")

    for card in cards:
        title_el = (
            card.find("h2")
            or card.find("h3")
            or card.find("h1")
        )
        title = _get_text_or_none(title_el)

        description_el = card.find("p")
        description = _get_text_or_none(description_el)

        price = _find_price(card)
        location = _find_location(card)
        property_type = _find_property_type(card)
        bedrooms = _find_bedrooms(card)
        bathrooms = _find_bathrooms(card)
        area = _find_area(card)
        energy_class = _find_energy_class(card)
        publisher = _find_publisher(card)
        contact = _find_contact(card)
        date_posted = _find_date_posted(card)

        rel_url = _find_link(card)
        full_url = (
            urljoin(IMMOWEB_BASE_URL, rel_url) if rel_url else None
        )
        listing_id = extract_listing_id_from_url(full_url) if full_url else None

        photos = _find_photos(card)

        # Skip cards that don't look like real listings
        if not title and not full_url:
            continue

        listing: Dict[str, Any] = {
            "id": listing_id,
            "url": full_url,
            "title": title,
            "description": description,
            "price": price,
            "photos": photos,
            "location": location,
            "propertyType": property_type,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "area": area,
            "energyClass": energy_class,
            "publisher": publisher,
            "contact": contact,
            "views": None,
            "datePosted": date_posted,
            "apify_monitoring_status": "unknown",
            "searchUrl": search_url,
        }

        listings.append(listing)

    return listings