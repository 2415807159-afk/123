from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


SCRIPT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CONFIG_FILE = os.path.join(ROOT_DIR, "config.yaml")
SEEN_IDS_FILE = os.path.join(ROOT_DIR, "archive", "journal_seen.json")
RANGE_TOKEN_RE = re.compile(r"^\d{8}-\d{8}$")
TAG_RE = re.compile(r"<[^>]+>")
DEFAULT_MAX_RECORDS_PER_JOURNAL = 120
DEFAULT_ROWS_PER_PAGE = 100
DEFAULT_SOURCE_NAME = "journal-crossref"
DEFAULT_REQUEST_RETRIES = 3


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def load_config() -> dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        log("[WARN] 未安装 PyYAML，无法解析 config.yaml。")
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        log(f"[WARN] 读取 config.yaml 失败：{exc}")
        return {}
    return data if isinstance(data, dict) else {}


def load_journal_watch_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    root = config if isinstance(config, dict) else load_config()
    section = root.get("journal_watch") or {}
    return section if isinstance(section, dict) else {}


def journal_watch_enabled(config: dict[str, Any] | None = None) -> bool:
    return bool(load_journal_watch_config(config).get("enabled"))


def resolve_days_window(default_days: int = 30) -> int:
    config = load_config()
    journal_cfg = load_journal_watch_config(config)
    value = journal_cfg.get("days_window")
    if value is None:
        value = ((config.get("arxiv_paper_setting") or {}) if isinstance(config, dict) else {}).get(
            "days_window"
        )
    try:
        return max(int(value), 1)
    except Exception:
        return max(default_days, 1)


def resolve_publication_window(days: int) -> tuple[datetime, datetime, str]:
    token = str(os.getenv("DPR_RUN_DATE") or "").strip()
    safe_days = max(int(days or 1), 1)
    now = datetime.now(timezone.utc)

    if re.match(r"^\d{8}$", token):
        if safe_days > 1:
            start = now - timedelta(days=safe_days)
            return start, now, f"rolling:{safe_days}d(token={token})"
        day = datetime.strptime(token, "%Y%m%d").replace(tzinfo=timezone.utc)
        return day, day + timedelta(days=1), f"single-day:{token}"

    matched = RANGE_TOKEN_RE.match(token)
    if matched:
        start_raw, end_raw = token.split("-", 1)
        start = datetime.strptime(start_raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_raw, "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        return start, end, f"range:{token}"

    start = now - timedelta(days=safe_days)
    return start, now, f"rolling:{safe_days}d"


def format_pub_date(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def normalize_title(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize_storage_id(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("https://doi.org/", "")
    text = text.replace("http://doi.org/", "")
    text = text.replace("doi:", "")
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def strip_jats(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_authors(item: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = str(author.get("name") or "").strip()
        if not name:
            given = str(author.get("given") or "").strip()
            family = str(author.get("family") or "").strip()
            name = " ".join(part for part in (given, family) if part).strip()
        if name and name not in result:
            result.append(name)
    return result


def extract_crossref_datetime(item: dict[str, Any]) -> datetime | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        payload = item.get(key)
        if not isinstance(payload, dict):
            continue
        parts = payload.get("date-parts") or []
        if not parts or not isinstance(parts, list):
            continue
        first = parts[0] if parts else []
        if not isinstance(first, list) or not first:
            continue
        try:
            year = int(first[0])
            month = int(first[1]) if len(first) >= 2 else 1
            day = int(first[2]) if len(first) >= 3 else 1
            return datetime(year, month, day, tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def select_best_links(item: dict[str, Any], doi: str) -> tuple[str, str]:
    pdf_url = ""
    for link in item.get("link") or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("URL") or "").strip()
        content_type = str(link.get("content-type") or "").strip().lower()
        intended = str(link.get("intended-application") or "").strip().lower()
        if not url:
            continue
        if "pdf" in content_type or intended == "text-mining" and url.lower().endswith(".pdf") or url.lower().endswith(".pdf"):
            pdf_url = url
            break

    primary_url = ""
    resource = item.get("resource")
    if isinstance(resource, dict):
        primary = resource.get("primary")
        if isinstance(primary, dict):
            primary_url = str(primary.get("URL") or "").strip()

    landing_url = primary_url or str(item.get("URL") or "").strip()
    if not landing_url and doi:
        landing_url = f"https://doi.org/{doi}"
    return landing_url, pdf_url


def normalize_journal_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    items = config.get("journals") or []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            title = item.strip()
            aliases: list[str] = []
        elif isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            aliases = [str(v).strip() for v in (item.get("aliases") or []) if str(v).strip()]
        else:
            continue
        if not title:
            continue
        normalized.append({"title": title, "aliases": aliases})
    return normalized


def journal_matches(target_title: str, aliases: list[str], container_titles: list[str]) -> bool:
    valid = {normalize_title(target_title)}
    valid.update(normalize_title(alias) for alias in aliases if alias)
    actual = {normalize_title(title) for title in container_titles if title}
    actual.discard("")
    return bool(valid & actual)


def parse_crossref_work(item: dict[str, Any], target_title: str, aliases: list[str]) -> dict[str, Any] | None:
    doi = str(item.get("DOI") or "").strip().lower()
    if not doi:
        return None

    container_titles = [str(v).strip() for v in (item.get("container-title") or []) if str(v).strip()]
    if not journal_matches(target_title, aliases, container_titles):
        return None

    titles = [str(v).strip() for v in (item.get("title") or []) if str(v).strip()]
    title = titles[0] if titles else ""
    if not title:
        return None

    journal_title = container_titles[0] if container_titles else target_title
    published_dt = extract_crossref_datetime(item)
    landing_url, pdf_url = select_best_links(item, doi)
    subjects = [str(v).strip() for v in (item.get("subject") or []) if str(v).strip()]
    paper_id = doi

    return {
        "id": paper_id,
        "source": DEFAULT_SOURCE_NAME,
        "title": title,
        "abstract": strip_jats(str(item.get("abstract") or "").strip()),
        "authors": extract_authors(item),
        "primary_category": journal_title,
        "categories": subjects,
        "published": format_pub_date(published_dt),
        "link": landing_url,
        "pdf_url": pdf_url,
        "journal": journal_title,
        "doi": doi,
        "publisher": str(item.get("publisher") or "").strip(),
        "content_type": str(item.get("type") or "").strip(),
        "storage_id": normalize_storage_id(paper_id),
    }


def build_crossref_headers(mailto: str) -> dict[str, str]:
    contact = f" ({mailto})" if mailto else ""
    return {
        "User-Agent": f"daily-paper-reader-journal-watch/1.0{contact}",
        "Accept": "application/json",
    }


def fetch_crossref_journal_works(
    *,
    title: str,
    aliases: list[str],
    start_dt: datetime,
    end_dt: datetime,
    mailto: str,
    max_records: int,
    rows_per_page: int,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    cursor = "*"
    session = requests.Session()
    headers = build_crossref_headers(mailto)
    select_fields = ",".join(
        [
            "DOI",
            "title",
            "abstract",
            "author",
            "issued",
            "published",
            "published-print",
            "published-online",
            "created",
            "URL",
            "link",
            "resource",
            "container-title",
            "publisher",
            "subject",
            "type",
        ]
    )

    while len(collected) < max_records:
        params = {
            "filter": ",".join(
                [
                    f"from-pub-date:{start_dt.strftime('%Y-%m-%d')}",
                    f"until-pub-date:{(end_dt - timedelta(days=0)).strftime('%Y-%m-%d')}",
                    f"container-title:{title}",
                ]
            ),
            "sort": "published",
            "order": "desc",
            "rows": min(rows_per_page, max_records - len(collected)),
            "cursor": cursor,
            "select": select_fields,
        }
        if mailto:
            params["mailto"] = mailto

        payload = None
        last_error: Exception | None = None
        for attempt in range(1, DEFAULT_REQUEST_RETRIES + 1):
            try:
                resp = session.get(
                    "https://api.crossref.org/works",
                    params=params,
                    headers=headers,
                    timeout=90,
                )
                if resp.status_code == 429 and attempt < DEFAULT_REQUEST_RETRIES:
                    time.sleep(1.0 * attempt)
                    continue
                resp.raise_for_status()
                payload = resp.json() or {}
                break
            except Exception as exc:
                last_error = exc
                if attempt >= DEFAULT_REQUEST_RETRIES:
                    raise
                time.sleep(1.0 * attempt)
        if payload is None:
            raise last_error or RuntimeError("Crossref 返回空响应")
        message = payload.get("message") or {}
        items = message.get("items") or []
        if not isinstance(items, list) or not items:
            break

        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            paper = parse_crossref_work(raw_item, title, aliases)
            if not paper:
                continue
            pid = str(paper.get("id") or "").strip()
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            collected.append(paper)
            if len(collected) >= max_records:
                break

        next_cursor = str(message.get("next-cursor") or "").strip()
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        if len(items) < int(params["rows"]):
            break
        time.sleep(0.4)

    return collected


def load_seen_ids() -> set[str]:
    if not os.path.exists(SEEN_IDS_FILE):
        return set()
    try:
        with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception:
        return set()
    raw_ids = payload.get("ids") or []
    if not isinstance(raw_ids, list):
        return set()
    return {str(v).strip() for v in raw_ids if str(v).strip()}


def save_seen_ids(ids: set[str]) -> None:
    os.makedirs(os.path.dirname(SEEN_IDS_FILE), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ids": sorted({str(v).strip() for v in ids if str(v).strip()}),
    }
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def merge_papers_by_id(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in existing + incoming:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if not pid:
            continue
        current = merged.get(pid) or {}
        next_item = dict(current)
        next_item.update(item)
        merged[pid] = next_item

    def sort_key(item: dict[str, Any]) -> tuple[str, str]:
        published = str(item.get("published") or "").strip()
        pid = str(item.get("id") or "").strip()
        return (published, pid)

    return sorted(merged.values(), key=sort_key, reverse=True)


def default_raw_output_path(run_token: str) -> str:
    return os.path.join(ROOT_DIR, "archive", run_token, "raw", f"arxiv_papers_{run_token}.json")


def run_journal_fetch(days: int | None = None, ignore_seen: bool = False, output_path: str | None = None) -> dict[str, Any]:
    config = load_config()
    journal_cfg = load_journal_watch_config(config)
    if not journal_cfg.get("enabled"):
        return {"enabled": False, "fetched": 0, "added": 0, "total": 0, "output_path": output_path or ""}

    journals = normalize_journal_entries(journal_cfg)
    if not journals:
        log("[WARN] journal_watch 已启用，但 journals 列表为空。")
        return {"enabled": True, "fetched": 0, "added": 0, "total": 0, "output_path": output_path or ""}

    days_window = max(int(days or resolve_days_window()), 1)
    start_dt, end_dt, window_desc = resolve_publication_window(days_window)
    run_token = str(os.getenv("DPR_RUN_DATE") or "").strip()
    if not re.match(r"^\d{8}$", run_token) and not RANGE_TOKEN_RE.match(run_token):
        run_token = datetime.now(timezone.utc).strftime("%Y%m%d")
    raw_path = output_path or default_raw_output_path(run_token)
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)

    mailto = str(journal_cfg.get("crossref_mailto") or "").strip()
    max_records = max(int(journal_cfg.get("max_records_per_journal") or DEFAULT_MAX_RECORDS_PER_JOURNAL), 1)
    rows_per_page = max(int(journal_cfg.get("rows_per_page") or DEFAULT_ROWS_PER_PAGE), 1)
    seen_ids = set() if ignore_seen else load_seen_ids()
    updated_seen = set(seen_ids)

    fetched_total = 0
    added_total = 0
    incoming: list[dict[str, Any]] = []

    log(
        f"[INFO] 期刊追踪启动：journals={len(journals)} days_window={days_window} "
        f"window={window_desc} raw_path={raw_path}"
    )

    for journal in journals:
        title = str(journal.get("title") or "").strip()
        aliases = [str(v).strip() for v in (journal.get("aliases") or []) if str(v).strip()]
        if not title:
            continue
        try:
            items = fetch_crossref_journal_works(
                title=title,
                aliases=aliases,
                start_dt=start_dt,
                end_dt=end_dt,
                mailto=mailto,
                max_records=max_records,
                rows_per_page=rows_per_page,
            )
        except Exception as exc:
            log(f"[WARN] 抓取期刊失败：{title} | {exc}")
            continue

        fetched_total += len(items)
        new_items = []
        for paper in items:
            pid = str(paper.get("id") or "").strip()
            if not pid:
                continue
            updated_seen.add(pid)
            if pid in seen_ids:
                continue
            new_items.append(paper)
        incoming.extend(new_items)
        added_total += len(new_items)
        log(f"[INFO] 期刊完成：{title} | fetched={len(items)} new={len(new_items)}")

    existing: list[dict[str, Any]] = []
    if os.path.exists(raw_path):
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                loaded = json.load(f) or []
                if isinstance(loaded, list):
                    existing = loaded
        except Exception as exc:
            log(f"[WARN] 读取已有 raw 文件失败，将仅写入期刊数据：{exc}")

    merged = merge_papers_by_id(existing, incoming)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    if not ignore_seen:
        save_seen_ids(updated_seen)

    log(
        f"[INFO] 期刊追踪写入完成：existing={len(existing)} incoming={len(incoming)} "
        f"merged={len(merged)} output={raw_path}"
    )
    return {
        "enabled": True,
        "fetched": fetched_total,
        "added": added_total,
        "total": len(merged),
        "output_path": raw_path,
        "window": window_desc,
    }
