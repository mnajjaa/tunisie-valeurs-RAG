"""
Scraper service for Tunisie Valeurs research notes.
Adapted from notes_scraper.py - keeps fallback logic and request patterns.
"""

import datetime as dt
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_URL = "https://www.tunisievaleurs.com/nos-publications/notes-de-recherche/"
NOTES_FEED_URL = "https://data.tunisievaleurs.com/data/ww2_rech.aspx?t=F&l=F&s=200"
NOTES_DETAILS_URL = "https://data.tunisievaleurs.com/ww2_showdetart.aspx?artid={artid}"
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

USER_AGENT = "Mozilla/5.0 (compatible; tunisie-valeurs-rag/1.0)"

logger = logging.getLogger(__name__)


def normalize_text(value: str) -> str:
    """Normalize unicode text for comparison."""
    if not value:
        return ""
    import unicodedata
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower().strip()


def parse_date(text: str) -> tuple[Optional[dt.date], Optional[str]]:
    """Extract date from text using regex. Returns (date_obj, date_str)."""
    match = DATE_RE.search(text or "")
    if not match:
        return None, None
    date_str = match.group(1)
    return dt.datetime.strptime(date_str, "%d/%m/%Y").date(), date_str


def parse_rfc_date(text: str) -> Optional[dt.date]:
    """Parse RFC 2822 date format."""
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError):
        return None


def count_dates(text: str) -> int:
    """Count date occurrences in text."""
    return len(DATE_RE.findall(text or ""))


def fetch_html(url: str, *, timeout: int = 30) -> str:
    """Fetch HTML from URL with proper headers."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def find_notes_section(soup: BeautifulSoup):
    """Locate the research notes section in page."""
    for header in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        label = normalize_text(header.get_text(" ", strip=True))
        if "notes de recherche" in label:
            return header.find_parent(["section", "div"]) or header.parent
    return soup


def find_card_candidates(root):
    """Find DOM card candidates containing date + link."""
    candidates = []
    seen = set()
    for text_node in root.find_all(string=DATE_RE):
        current = text_node.parent
        best = None
        for _ in range(6):
            if current is None:
                break
            text = current.get_text(" ", strip=True)
            if count_dates(text) == 1 and current.find("a", href=True):
                best = current
            if count_dates(text) > 1:
                break
            current = current.parent
        if best is None:
            continue
        signature = normalize_text(best.get_text(" ", strip=True))[:120]
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(best)
    return candidates


def pick_title(card) -> Optional[str]:
    """Extract title from card."""
    for tag in card.find_all(["h1", "h2", "h3", "h4"]):
        text = tag.get_text(" ", strip=True)
        if text:
            return text
    for tag in card.find_all(["strong", "b"]):
        text = tag.get_text(" ", strip=True)
        if text:
            return text
    return None


def pick_details_link(card) -> Optional[str]:
    """Extract details link from card."""
    for anchor in card.find_all("a", href=True):
        label = normalize_text(anchor.get_text(" ", strip=True))
        if "plus de details" in label or label == "details":
            return anchor.get("href")
    for anchor in card.find_all("a", href=True):
        href = anchor.get("href", "")
        if href and not href.startswith("#") and "javascript" not in href.lower():
            return href
    return None


def find_pdf_link(details_url: str, *, timeout: int = 30) -> Optional[str]:
    """Find PDF link from details page."""
    try:
        html = fetch_html(details_url, timeout=timeout)
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if ".pdf" in href.lower():
                return urljoin(details_url, href)
        for tag in soup.find_all(attrs=True):
            for value in tag.attrs.values():
                if isinstance(value, str) and ".pdf" in value.lower():
                    return urljoin(details_url, value)
        for anchor in soup.find_all("a", href=True):
            label = normalize_text(anchor.get_text(" ", strip=True))
            if "telecharg" in label or "download" in label:
                return urljoin(details_url, anchor.get("href", ""))
    except Exception:
        logger.exception("Failed to find PDF link for %s", details_url)
    return None


def xml_text(element, tag: str) -> Optional[str]:
    """Extract text from XML element."""
    if element is None:
        return None
    node = element.find(tag)
    if node is None or node.text is None:
        return None
    return node.text.strip()


def extract_artid(link: str) -> Optional[str]:
    """Extract article ID from URL."""
    if not link:
        return None
    try:
        parsed = urlparse(link)
        params = parse_qs(parsed.query)
        artid = params.get("artid")
        if artid:
            return artid[0]
    except Exception:
        return None
    return None


def fetch_note_details(session: requests.Session, artid: str, *, timeout: int = 30) -> tuple[Optional[str], Optional[str]]:
    """Fetch note details from API. Returns (link, pub_date)."""
    if not artid:
        return None, None
    url = NOTES_DETAILS_URL.format(artid=artid)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    link = xml_text(root, "link")
    pub_date = xml_text(root, "pubDate")
    return link, pub_date


def scrape_notes_api(min_date: dt.date, *, timeout: int = 30) -> list[dict]:
    """
    Scrape notes from Tunisie Valeurs API endpoint.
    Returns list of notes with title, date, pdf_link, details_link.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    response = session.get(NOTES_FEED_URL, timeout=timeout)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    items = []
    for item in root.findall(".//item"):
        title = xml_text(item, "title")
        pub_date = xml_text(item, "pubDate")
        link = xml_text(item, "link")
        date_obj = parse_rfc_date(pub_date)
        artid = extract_artid(link)
        pdf_link = None
        detail_date = None
        if artid:
            try:
                pdf_link, detail_date = fetch_note_details(session, artid, timeout=timeout)
            except Exception:
                pdf_link = None
        detail_obj, _ = parse_date(detail_date or "")
        date_obj = detail_obj or date_obj
        if not date_obj:
            continue
        if date_obj.year != 2026:
            continue
        if date_obj < min_date:
            continue
        items.append(
            {
                "title": title,
                "date": date_obj.isoformat(),
                "pdf_link": pdf_link,
                "details_link": link,
            }
        )
    items.sort(key=lambda item: item["date"])
    return items


def scrape_notes(url: str, min_date: dt.date, *, timeout: int = 30) -> list[dict]:
    """
    Scrape notes from HTML page. Falls back to API if no results.
    Returns list of notes with title, date, pdf_link, details_link.
    """
    html = fetch_html(url, timeout=timeout)
    soup = BeautifulSoup(html, "html.parser")
    root = find_notes_section(soup)
    candidates = find_card_candidates(root)
    items = []
    seen = set()
    for card in candidates:
        text = card.get_text(" ", strip=True)
        date_obj, _ = parse_date(text)
        if not date_obj:
            continue
        if date_obj.year != 2026:
            continue
        if date_obj < min_date:
            continue
        title = pick_title(card)
        details_link = pick_details_link(card)
        if not details_link:
            continue
        details_url = urljoin(url, details_link)
        pdf_link = None
        if details_link.lower().endswith(".pdf"):
            pdf_link = details_url
        else:
            try:
                pdf_link = find_pdf_link(details_url, timeout=timeout)
            except Exception:
                pdf_link = None
        if not title:
            title = DATE_RE.sub("", text).strip()
        key = (title or "", date_obj.isoformat(), pdf_link or details_url)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "title": title,
                "date": date_obj.isoformat(),
                "pdf_link": pdf_link,
                "details_link": details_url,
            }
        )
    items.sort(key=lambda item: item["date"])
    if items:
        return items
    # Fallback to API
    return scrape_notes_api(min_date, timeout=timeout)


def get_notes(min_date: dt.date, *, timeout: int = 30) -> list[dict]:
    """
    Public interface: fetch research notes from Tunisie Valeurs.
    
    Args:
        min_date: Only return notes published on or after this date
        timeout: HTTP request timeout in seconds
    
    Returns:
        List of note dictionaries with keys: title, date (ISO format), pdf_link, details_link
    """
    return scrape_notes(DEFAULT_URL, min_date, timeout=timeout)
