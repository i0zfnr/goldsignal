import calendar
import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from bs4 import BeautifulSoup
from icalendar import Calendar

from .config import CALENDAR_MAX_AGE, NEWS_AFTER, NEWS_BEFORE, NY
from .market import REPLAY_START

BLS = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA = "https://www.bea.gov/news/schedule/full"
FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
log = logging.getLogger(__name__)


class CalendarSource(Protocol):
    def __call__(self, now: float) -> list[dict]: ...


def event(source, title, ts, url, **values):
    return dict(source=source, title=title, time=int(ts), url=url, actual=values.get("actual"),
                forecast=values.get("forecast"), previous=values.get("previous"))


def download(url):
    result = httpx.get(url, timeout=6, follow_redirects=True, headers={"User-Agent": "Goldsignal/1.0"})
    result.raise_for_status()
    return result.content


def bls_events(now):
    keys = {"consumer price index": "CPI", "producer price index": "PPI", "employment situation": "NFP"}
    rows = []
    for item in Calendar.from_ical(download(BLS)).walk("VEVENT"):
        summary = str(item["SUMMARY"])
        match = next((abbr for key, abbr in keys.items() if summary.lower().startswith(key)), None)
        if match:
            stamp = item.decoded("DTSTART")
            if isinstance(stamp, datetime):
                ts = stamp.replace(tzinfo=NY).timestamp() if stamp.tzinfo is None else stamp.timestamp()
                rows.append(event("BLS", f"{match} · {summary}", ts, str(item.get("URL", BLS))))
    return rows


def bea_events(now):
    year = datetime.fromtimestamp(now, NY).year
    rows = []
    for url, schedule_year in ((BEA, year), ("https://www.bea.gov/news/schedule/next-year", year + 1)):
        page = BeautifulSoup(download(url), "html.parser")
        for row in page.select("tr"):
            title, day, time = row.select_one(".release-title"), row.select_one(".release-date"), row.select_one(".scheduled-date small")
            if not all((title, day, time)) or not title.get_text(strip=True).lower().startswith("personal income and outlays"):
                continue
            stamp = datetime.strptime(f"{day.get_text(strip=True)} {schedule_year} {time.get_text(strip=True)}",
                                      "%B %d %Y %I:%M %p").replace(tzinfo=NY)
            link = row.select_one("a[href]")
            rows.append(event("BEA", f"PCE · {title.get_text(strip=True)}", stamp.timestamp(),
                              urljoin(url, link["href"]) if link else url))
    return rows


def fed_events(now):
    page = BeautifulSoup(download(FED), "html.parser")
    rows = []
    for panel in page.select(".panel"):
        title = panel.select_one(".panel-heading")
        year = re.search(r"\b20\d{2}\b", title.get_text() if title else "")
        if not year:
            continue
        for month in panel.select(".fomc-meeting__month"):
            dates = month.find_next_sibling(class_="fomc-meeting__date")
            parts = re.findall(r"\d+", dates.get_text()) if dates else []
            if parts:
                month_name = month.get_text(strip=True).split("/")[-1].strip()
                month_number = next((index for index, name in enumerate(calendar.month_name) if
                                     name and name.lower().startswith(month_name.lower().rstrip("."))), None)
                if month_number is None:
                    raise ValueError(f"Unexpected FOMC month: {month_name}")
                stamp = datetime(int(year[0]), month_number, int(parts[-1]), 14, tzinfo=NY)
                rows.append(event("Fed", "FOMC decision", stamp.timestamp(), FED))
    return rows


def refresh(demo, now, previous, readers: dict[str, CalendarSource] | None = None):
    if demo:
        week = int((now - REPLAY_START) // (7 * 86400))
        start = REPLAY_START + week * 7 * 86400
        return dict(refreshed=now, events=[event("Fixture", "Mock USD inflation release",
                                               start + (900 if week % 3 == 2 else 5400), None)],
                    sources={"Fixture": now}, headlines=[dict(title="Replay calendar fixture loaded",
                    time=start - 600, first_seen=start, source="Fixture", url=None)], errors={})
    state = dict(previous or {})
    state.update(refreshed=now, errors={})
    state.setdefault("sources", {})
    state.setdefault("events", [])
    readers = readers or {"BLS": bls_events, "BEA": bea_events, "Fed": fed_events}
    for name, reader in readers.items():
        try:
            rows = reader(now)
            if not any(row["time"] >= now for row in rows):
                raise ValueError("No upcoming releases parsed")
            state["events"] = [row for row in state["events"] if row["source"] != name] + rows
            state["sources"][name] = now
        except Exception as exc:
            log.warning("%s calendar refresh failed: %s", name, exc)
            state["errors"][name] = "Calendar refresh failed"
    known = {row["id"]: row for row in state.get("headlines", [])}
    for url in [RSS, *filter(None, os.getenv("HEADLINE_RSS_URLS", "").split(","))]:
        try:
            feed = feedparser.parse(download(url))
            if not feed.entries:
                raise ValueError("Feed had no entries")
            state["sources"][urlsplit(url).netloc + " RSS"] = now
            for item in feed.entries[:30]:
                link = item.get("link", "")
                stamp = item.get("published_parsed") or item.get("updated_parsed")
                if not stamp or urlsplit(link).scheme not in ("http", "https"):
                    continue
                title = BeautifulSoup(item.get("title", ""), "html.parser").get_text(" ", strip=True)
                key = hashlib.sha256(" ".join(title.casefold().split()).encode()).hexdigest()
                if title:
                    known.setdefault(key, dict(id=key, source=urlsplit(url).netloc, url=link, title=title,
                                               time=calendar.timegm(stamp), first_seen=now))
        except Exception as exc:
            log.warning("Headline refresh failed for %s: %s", urlsplit(url).netloc, exc)
            state["errors"][urlsplit(url).netloc + " RSS"] = "Headline refresh failed"
    state["headlines"] = sorted(known.values(), key=lambda row: row["time"], reverse=True)[:200]
    return state


def restriction(state, now, demo):
    sources = state.get("sources", {})
    for key in (("Fixture",) if demo else ("BLS", "BEA", "Fed")):
        if key not in sources or now - sources[key] > CALENDAR_MAX_AGE:
            return f"{key} calendar is stale or unavailable"
    for item in state.get("events", []):
        if item["time"] - NEWS_BEFORE <= now <= item["time"] + NEWS_AFTER:
            return f"Calendar pause: {item['title']}"
    return None
