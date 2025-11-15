from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional, List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from mcp.server.fastmcp import FastMCP

import datetime

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_FILE = Path("/app/logs-dir/logs.jsonl")
CI_STATUS_FILE = Path("/app/logs-dir/ci-status.json")

mcp = FastMCP("RpgLedger")
dev_mcp = FastMCP("RpgLedgerDev")
app = FastAPI(title="RPG Ledger MCP + UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _campaign_path(campaign_id: str) -> Path:
    safe = "".join(c for c in campaign_id if c.isalnum() or c in "-_")
    return DATA_DIR / f"{safe}.json"


def _load_campaign(campaign_id: str) -> dict[str, Any]:
    path = _campaign_path(campaign_id)
    if not path.exists():
        raise FileNotFoundError(f"Campaign {campaign_id!r} not found")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_campaign(campaign_id: str, data: dict[str, Any]) -> None:
    path = _campaign_path(campaign_id)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _log_event(event: dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault(
        "ts",
        datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    )
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _find_character(data: dict[str, Any], char_id: str) -> dict[str, Any]:
    chars = data.get("characters") or []
    for ch in chars:
        if ch.get("id") == char_id:
            return ch
    raise KeyError(f"Character {char_id!r} not found in campaign {data.get('id')}")


@mcp.tool()
def list_campaigns() -> list[dict[str, str]]:
    campaigns: list[dict[str, str]] = []
    if not DATA_DIR.is_dir():
        return campaigns

    for filename in DATA_DIR.iterdir():
        if not filename.name.endswith(".json"):
            continue
        try:
            with filename.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        cid = data.get("id") or filename.stem
        name = data.get("name") or cid
        campaigns.append({"id": cid, "name": name})
    return campaigns


@mcp.tool()
def get_campaign(campaign_id: str) -> dict[str, Any]:
    return _load_campaign(campaign_id)


@mcp.tool()
def get_character(campaign_id: str, char_id: str) -> dict[str, Any]:
    data = _load_campaign(campaign_id)
    ch = _find_character(data, char_id)
    return ch



@mcp.tool()
def mutate(
    campaign_id: str,
    op: str,
    char_id: Optional[str] = None,
    amount: Optional[int] = None,
    text: Optional[str] = None,
    value: Optional[Any] = None,
) -> dict[str, Any]:
    """Modyfikacja stanu kampanii / postaci.

    Obsługiwane op-y (rozszerzalne):

    - gold_add           – zmiana złota postaci (wymaga char_id, amount)
    - hp_add             – zmiana HP postaci (wymaga char_id, amount)
    - xp_add             – zmiana XP postaci (wymaga char_id, amount)
    - note_append        – dopisz notkę (jeśli jest char_id → do postaci, inaczej do kampanii)

    Dodatkowe op-y dla pełnego legera:

    - char_note_add      – dopisz notkę TYLKO do postaci (wymaga char_id, text)
    - campaign_note_add  – dopisz notkę TYLKO do kampanii (wymaga text)
    - day_add            – dodaj do dnia kampanii (amount)
    - day_set            – ustaw dzień kampanii (amount)
    - location_set       – ustaw lokację kampanii (value jako string)
    - inventory_add      – dodaj przedmiot do ekwipunku postaci
                           value: JSON { "id": str, "name"?: str, "qty"?: int }
    - inventory_remove   – usuń / zmniejsz ilość przedmiotu w ekwipunku postaci
                           value: JSON { "id": str, "qty"?: int }
    - world_flag_set     – flaga stanu świata
                           value: JSON { "key": str, "value": any }
    - quest_update       – utwórz / zaktualizuj questa
                           value: JSON { "id": str, "title"?: str, "status"?: str, "notes"?: str }
    - faction_rep_add    – zmień reputację u frakcji
                           value: JSON { "id": str, "name"?: str, "delta"?: int }
    - history_log        – tylko wpis do historii (bez modyfikacji kampanii),
                           value: dowolny JSON reprezentujący zdarzenie
    """
    data = _load_campaign(campaign_id)

    character: Optional[dict[str, Any]] = None
    if char_id is not None:
        character = _find_character(data, char_id)

    def require_amount() -> int:
        if amount is None:
            raise ValueError("amount is required for this operation")
        return int(amount)

    # Parsowanie value jako JSON (jeśli to ma sens)
    parsed_value: Any
    if value is None:
        parsed_value = None
    elif isinstance(value, str):
        try:
            parsed_value = json.loads(value)
        except Exception:
            parsed_value = value
    else:
        parsed_value = value

    # ----------------- Operacje na postaciach -----------------

    if op == "gold_add":
        if character is None:
            raise ValueError("char_id is required for gold_add")
        delta = require_amount()
        current = int(character.get("gold") or 0)
        character["gold"] = current + delta

    elif op == "hp_add":
        if character is None:
            raise ValueError("char_id is required for hp_add")
        delta = require_amount()
        current = int(character.get("hp") or 0)
        new_hp = current + delta
        # Prosty clamp na 0, bez max_hp (na razie)
        if new_hp < 0:
            new_hp = 0
        character["hp"] = new_hp

    elif op == "xp_add":
        if character is None:
            raise ValueError("char_id is required for xp_add")
        delta = require_amount()
        current = int(character.get("xp") or 0)
        character["xp"] = current + delta

    elif op == "note_append":
        # Zachowujemy wsteczną kompatybilność:
        # jeśli jest char_id → notka do postaci, inaczej do kampanii.
        target = character if character is not None else data
        if not text:
            raise ValueError("text is required for note_append")
        existing = target.get("notes") or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        target["notes"] = existing + text

    elif op == "char_note_add":
        if character is None:
            raise ValueError("char_id is required for char_note_add")
        if not text:
            raise ValueError("text is required for char_note_add")
        existing = character.get("notes") or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        character["notes"] = existing + text

    elif op == "campaign_note_add":
        if not text:
            raise ValueError("text is required for campaign_note_add")
        existing = data.get("notes") or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        data["notes"] = existing + text

    # ----------------- Czas / miejsce -----------------

    elif op == "day_add":
        delta = require_amount()
        current = int(data.get("day") or 0)
        data["day"] = current + delta

    elif op == "day_set":
        new_day = require_amount()
        data["day"] = new_day

    elif op == "location_set":
        if value is None:
            raise ValueError("value is required for location_set")
        # Tu value traktujemy jako zwykły string (bez JSON)
        data["location"] = value

    # ----------------- Ekwipunek -----------------

    elif op == "inventory_add":
        if character is None:
            raise ValueError("char_id is required for inventory_add")
        if not isinstance(parsed_value, dict) or "id" not in parsed_value:
            raise ValueError("inventory_add requires JSON in 'value' with at least 'id'")
        item_id = str(parsed_value["id"])
        name = str(parsed_value.get("name", item_id))
        qty_raw = parsed_value.get("qty", 1)
        qty = int(qty_raw)
        if qty <= 0:
            raise ValueError("qty for inventory_add must be > 0")
        inventory = character.setdefault("inventory", [])
        existing = None
        for it in inventory:
            if it.get("id") == item_id:
                existing = it
                break
        if existing is not None:
            existing["qty"] = int(existing.get("qty") or 0) + qty
        else:
            inventory.append({"id": item_id, "name": name, "qty": qty})

    elif op == "inventory_remove":
        if character is None:
            raise ValueError("char_id is required for inventory_remove")
        if not isinstance(parsed_value, dict) or "id" not in parsed_value:
            raise ValueError("inventory_remove requires JSON in 'value' with at least 'id'")
        item_id = str(parsed_value["id"])
        qty_raw = parsed_value.get("qty", 1)
        qty = int(qty_raw)
        if qty <= 0:
            raise ValueError("qty for inventory_remove must be > 0")
        inventory = character.setdefault("inventory", [])
        remaining: list[dict[str, Any]] = []
        for it in inventory:
            if it.get("id") != item_id:
                remaining.append(it)
                continue
            current_qty = int(it.get("qty") or 0)
            new_qty = current_qty - qty
            if new_qty > 0:
                it["qty"] = new_qty
                remaining.append(it)
            # jeśli <= 0 → item znika całkiem
        character["inventory"] = remaining

    # ----------------- Stan świata / questy / frakcje -----------------

    elif op == "world_flag_set":
        if not isinstance(parsed_value, dict) or "key" not in parsed_value:
            raise ValueError("world_flag_set requires JSON in 'value' with 'key' and 'value'")
        key = str(parsed_value["key"])
        val = parsed_value.get("value")
        flags = data.setdefault("world_flags", {})
        flags[key] = val

    elif op == "quest_update":
        if not isinstance(parsed_value, dict) or "id" not in parsed_value:
            raise ValueError("quest_update requires JSON in 'value' with at least 'id'")
        qid = str(parsed_value["id"])
        quests = data.setdefault("quests", [])
        existing = None
        for q in quests:
            if q.get("id") == qid:
                existing = q
                break
        if existing is None:
            existing = {
                "id": qid,
                "title": str(parsed_value.get("title", qid)),
                "status": str(parsed_value.get("status", "open")),
                "notes": parsed_value.get("notes"),
            }
            quests.append(existing)
        else:
            if "title" in parsed_value and parsed_value["title"] is not None:
                existing["title"] = str(parsed_value["title"])
            if "status" in parsed_value and parsed_value["status"] is not None:
                existing["status"] = str(parsed_value["status"])
            if "notes" in parsed_value:
                existing["notes"] = parsed_value["notes"]

    elif op == "faction_rep_add":
        if not isinstance(parsed_value, dict) or "id" not in parsed_value:
            raise ValueError("faction_rep_add requires JSON in 'value' with at least 'id'")
        fid = str(parsed_value["id"])
        delta_raw = parsed_value.get("delta", 0)
        delta = int(delta_raw)
        name = str(parsed_value.get("name", fid))
        factions = data.setdefault("factions", [])
        existing = None
        for f in factions:
            if f.get("id") == fid:
                existing = f
                break
        if existing is None:
            existing = {"id": fid, "name": name, "rep": delta}
            factions.append(existing)
        else:
            existing["name"] = name
            existing["rep"] = int(existing.get("rep") or 0) + delta

    # ----------------- Tylko log historii -----------------

    elif op == "history_log":
        # Nie modyfikujemy kampanii, tylko zapisujemy zdarzenie.
        _log_event(
            {
                "type": "history",
                "campaign_id": campaign_id,
                "char_id": char_id,
                "amount": amount,
                "text": text,
                "value": parsed_value,
            }
        )
        return data

    else:
        raise ValueError(f"Unknown op: {op!r}")

    # Zapis zmian i log standardowego mutowania
    _save_campaign(campaign_id, data)

    _log_event(
        {
            "type": "mutate",
            "op": op,
            "campaign_id": campaign_id,
            "char_id": char_id,
            "amount": amount,
            "text": text,
            "value": value,
        }
    )

    return data


@mcp.tool()
def dev_todo(
    summary: str,
    details: Optional[str] = None,
    tags: Optional[List[str]] = None,
    campaign_id: Optional[str] = None,
    char_id: Optional[str] = None,
) -> dict[str, Any]:
    """Zapisz TODO dla dalszego rozwoju legera.

    Ubzyj tego narzdzia z poziomu MG/AI, aby odnotowab brakujc funkcjonalnoci
    (np. nowy typ mutacji, raport, integracj itp.).

    Zapis trafia do tego samego logu co inne zdarzenia (logs.jsonl) z typem "todo".
    """
    _log_event(
        {
            "type": "todo",
            "summary": summary,
            "details": details,
            "tags": tags or [],
            "campaign_id": campaign_id,
            "char_id": char_id,
            "done": False,
            "comment": "",
        }
    )
    return {"ok": True}


@dev_mcp.tool()
def dev_get_logs(
    limit: int = 100,
    event_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Zwróć ostatnie wpisy z logs.jsonl.

    Użyteczne dla diagnostyki z poziomu Dev MCP.
    Opcjonalnie można zawęzić po polu "type" (np. "mutate", "todo", "history").
    """
    if not LOG_FILE.exists():
        return []
    entries: List[dict[str, Any]] = []
    with LOG_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if event_type and obj.get("type") != event_type:
                continue
            entries.append(obj)
    entries.sort(key=lambda e: e.get("ts", ""))
    if limit and limit > 0:
        entries = entries[-limit:]
    entries.reverse()
    return entries


@dev_mcp.tool()
def dev_get_todos(limit: int = 50) -> list[dict[str, Any]]:
    """Zwróć ostatnie TODO zapisane przez dev_todo.

    Filtrowane po type == "todo" w logs.jsonl.
    """
    return dev_get_logs(limit=limit, event_type="todo")


@dev_mcp.tool()
def dev_request_restart(target: str = "stack") -> dict[str, Any]:
    """Zgłoś prośbę o restart stacka / serwisów.

    NIE wykonuje restartu samodzielnie – tylko zapisuje zdarzenie
    type == "dev_restart_request" w logs.jsonl. Skrypt CI / operator
    może ten log obserwować i wykonać właściwy restart.

    target: "stack", "gameserver", "mcp".
    """
    allowed = {"stack", "gameserver", "mcp"}
    if target not in allowed:
        raise ValueError(f"target must be one of {sorted(allowed)}")
    payload = {
        "type": "dev_restart_request",
        "target": target,
    }
    _log_event(payload)
    return {"ok": True, "requested": target}


@dev_mcp.tool()
def dev_get_ci_status() -> dict[str, Any]:
    """Zwróć status deployu/CI z pliku ci-status.json.

    Pipeline CI może zapisywać do /app/logs-dir/ci-status.json
    np. {"status": "ok" | "building" | "failed", ...}.
    Jeśli plik nie istnieje albo jest niepoprawny, zwracamy "unknown".
    """
    if not CI_STATUS_FILE.exists():
        return {"status": "unknown"}
    try:
        with CI_STATUS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": "unknown"}
    if not isinstance(data, dict):
        return {"status": "unknown"}
    if "status" not in data:
        data["status"] = "unknown"
    return data


@dev_mcp.tool()
def dev_wait_for_deploy(
    desired_status: str = "ok",
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> dict[str, Any]:
    """Czekaj aż CI/deploy osiągnie zadany status.

    Blokujący call po stronie Dev MCP: w pętli odpytuje dev_get_ci_status()
    co poll_interval_seconds, maksymalnie przez timeout_seconds.
    """
    start = time.time()
    last_status: dict[str, Any] = {}
    while True:
        last_status = dev_get_ci_status()
        if str(last_status.get("status")) == desired_status:
            break
        if time.time() - start >= timeout_seconds:
            break
        time.sleep(max(1, poll_interval_seconds))
    elapsed = int(time.time() - start)
    return {
        "desired_status": desired_status,
        "elapsed_seconds": elapsed,
        "status": last_status.get("status", "unknown"),
        "details": last_status,
    }


app.mount("/mcp", mcp.sse_app())
app.mount("/mcp-dev", dev_mcp.sse_app())
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_path = BASE_DIR / "static" / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/campaigns")
async def api_campaigns() -> list[dict[str, str]]:
    return list_campaigns()


@app.post("/api/mutate")
async def api_mutate(payload: dict[str, Any]) -> dict[str, Any]:
    return mutate(**payload)


@app.post("/api/todo-status")
async def api_todo_status(payload: dict[str, Any]) -> dict[str, Any]:
    todo_ts = payload.get("todo_ts")
    status = str(payload.get("status") or "open").lower()
    comment = payload.get("comment") or ""
    if not todo_ts:
        raise ValueError("todo_ts is required")

    if not LOG_FILE.exists():
        return {"ok": False, "error": "logs file not found"}

    import json as _json

    entries: list[dict[str, Any]] = []
    with LOG_FILE.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_json.loads(line))
            except Exception:
                continue

    for e in entries:
        if e.get("type") == "todo" and e.get("ts") == todo_ts:
            e["done"] = status == "done"
            e["comment"] = comment

    with LOG_FILE.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(_json.dumps(e, ensure_ascii=False) + "\n")

    return {"ok": True}


@app.get("/api/campaigns/{campaign_id}")
async def api_campaign(campaign_id: str) -> dict[str, Any]:
    return _load_campaign(campaign_id)


@app.get("/api/logs")
async def api_logs(limit: int = 100) -> list[dict[str, Any]]:
    if not LOG_FILE.exists():
        return []
    entries: List[dict[str, Any]] = []
    with LOG_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    entries.sort(key=lambda e: e.get("ts", ""))
    if limit and limit > 0:
        entries = entries[-limit:]
    entries.reverse()
    return entries
