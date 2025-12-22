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
import d20
import networkx as nx
import random

from rpg_ledger import storage
from rpg_ledger import npc_factory
from rpg_ledger import dice_service
from rpg_ledger import world_service
from rpg_ledger import mutation_service


BASE_DIR = Path(__file__).resolve().parent

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


def _find_character(data: dict[str, Any], char_id: str) -> dict[str, Any]:
    chars = data.get("characters") or []
    for ch in chars:
        if ch.get("id") == char_id:
            return ch
    raise KeyError(f"Character {char_id!r} not found in campaign {data.get('id')}")


@mcp.tool()
def list_campaigns() -> list[dict[str, str]]:
    campaigns: list[dict[str, str]] = []
    if not storage.DATA_DIR.is_dir():
        return campaigns

    for filename in storage.DATA_DIR.iterdir():
        if not filename.name.endswith(".json"):
            continue
        # Pomijamy pliki szablonów (np. kampania-test.template.json)
        if filename.name.endswith(".template.json"):
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
    return storage.load_campaign(campaign_id)


@mcp.tool()
def get_character(campaign_id: str, char_id: str) -> dict[str, Any]:
    data = storage.load_campaign(campaign_id)
    ch = _find_character(data, char_id)
    return ch


@mcp.tool()
def list_locations(campaign_id: str) -> list[dict[str, Any]]:
    """Zwróć listę lokacji kampanii (`campaign.locations`)."""
    data = storage.load_campaign(campaign_id)
    return list(data.get("locations") or [])


@mcp.tool()
def create_campaign(
    campaign_id: str,
    name: Optional[str] = None,
    from_campaign_id: Optional[str] = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Utwórz nową kampanię i zapisz ją w `data/{campaign_id}.json`.

    - `campaign_id` – docelowe id kampanii (nazwa pliku bez `.json`), np. `smolenia-na-wieczne-tymczasem`
    - `name` – opcjonalna nazwa wyświetlana (jeśli brak, użyje `campaign_id`)
    - `from_campaign_id`:
        - jeśli **pominięte** / `null` → tworzona jest **pusta, nowa kampania** z bazową strukturą
        - jeśli podane → nowa kampania będzie **kopią istniejącej** (snapshot), z podmienionym `id` i `name`
    - `overwrite` – jeśli `true`, pozwala nadpisać istniejący plik kampanii o tym samym id

    Użycie:
    - **nowa kampania od zera**:
        - `create_campaign(campaign_id=\"smolenia-na-wieczne-tymczasem\", name=\"Smolenia na wieczne tymczasem\")`
        - *nie ustawiaj* `from_campaign_id`, jeśli nie chcesz kopiować starej kampanii.
    - **kopiowanie istniejącej kampanii jako szablonu**:
        - `create_campaign(campaign_id=\"kampania-kopia\", from_campaign_id=\"kampania-1\")`

    Skutek uboczny: zapis pliku `data/{campaign_id}.json` oraz wpis w logu kampanii (type=\"history\").
    """
    path = storage.campaign_path(campaign_id)
    if path.exists() and not overwrite:
        raise ValueError(f"campaign {campaign_id!r} already exists (set overwrite=True to replace)")

    if from_campaign_id:
        src = storage.load_campaign(from_campaign_id)
        data = json.loads(json.dumps(src))
        data["id"] = campaign_id
        data["name"] = name or src.get("name") or campaign_id
    else:
        data = {
            "id": campaign_id,
            "name": name or campaign_id,
            "day": 1,
            "location": "",
            "current_location_id": "",
            "notes": "",
            "locations": [],
            "connections": [],
            "characters": [],
            "world_flags": {},
            "quests": [],
            "factions": [],
        }

    storage.save_campaign(campaign_id, data)
    storage.log_event(
        {
            "type": "history",
            "campaign_id": campaign_id,
            "char_id": None,
            "amount": None,
            "text": f"create_campaign from={from_campaign_id}",
            "value": {
                "from_campaign_id": from_campaign_id,
                "name": data.get("name"),
            },
        }
    )
    return data


@mcp.tool()
def create_character(
    campaign_id: str,
    character: dict[str, Any],
) -> dict[str, Any]:
    """Dodaj nową postać do kampanii.

    - campaign_id: id kampanii
    - character: słownik z danymi postaci (name, class, level, hp, xp, stats, gold, inventory, notes, itp.)

    Jeśli character.id jest puste, zostanie wygenerowane z name w formie slug.
    Skutek uboczny: zapis kampanii oraz wpis typu \"mutate\" (op=\"create_character\").
    """
    data = storage.load_campaign(campaign_id)
    chars: list[dict[str, Any]] = data.setdefault("characters", [])

    payload = dict(character)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("character.name is required")

    cid_raw = str(payload.get("id") or "")
    if not cid_raw:
        base = "".join(c for c in name.lower() if c.isalnum() or c in "-_") or "char"
    else:
        base = "".join(c for c in cid_raw if c.isalnum() or c in "-_") or "char"

    existing_ids = {str(c.get("id") or "") for c in chars if c.get("id")}
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1

    payload["id"] = candidate
    chars.append(payload)

    storage.save_campaign(campaign_id, data)
    storage.log_event(
        {
            "type": "mutate",
            "op": "create_character",
            "campaign_id": campaign_id,
            "char_id": candidate,
            "amount": None,
            "text": f"create_character {name}",
            "value": {"id": candidate, "name": name},
        }
    )
    return data


@mcp.tool()
def update_character(
    campaign_id: str,
    char_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Zaktualizuj istniejącą postać w kampanii.

    - campaign_id: id kampanii
    - char_id: id postaci do aktualizacji
    - patch: słownik z polami do nadpisania (np. name, class, level, hp, stats, gold, notes)

    Skutek uboczny: zapis kampanii oraz wpis typu \"mutate\" (op=\"update_character\").
    """
    data = storage.load_campaign(campaign_id)
    ch = _find_character(data, char_id)

    allowed_simple = [
        "name",
        "class",
        "level",
        "xp",
        "hp",
        "alignment",
        "persona",
        "gold",
        "notes",
    ]

    for key in allowed_simple:
        if key in patch and patch[key] is not None:
            ch[key] = patch[key]

    if "stats" in patch and isinstance(patch["stats"], dict):
        ch["stats"] = dict(patch["stats"])
    if "inventory" in patch and isinstance(patch["inventory"], list):
        ch["inventory"] = list(patch["inventory"])

    storage.save_campaign(campaign_id, data)
    storage.log_event(
        {
            "type": "mutate",
            "op": "update_character",
            "campaign_id": campaign_id,
            "char_id": char_id,
            "amount": None,
            "text": "update_character",
            "value": patch,
        }
    )
    return data


@mcp.tool()
def upsert_location(
    campaign_id: str,
    location: dict[str, Any],
) -> dict[str, Any]:
    """Dodaj lub zaktualizuj jedną lokację w kampanii.

    - campaign_id: id kampanii
    - location: obiekt JSON z polami np. id, name, type, tags, description

    Jeśli lokacja z podanym id (lub name) istnieje, zostanie zaktualizowana.
    Jeśli nie istnieje, zostanie dodana nowa lokacja.

    Skutek uboczny: zapis kampanii oraz wpis typu \"mutate\" (op=\"upsert_location\").
    """
    return mutation_service.mutate(
        campaign_id=campaign_id,
        op="upsert_location",
        value=location,
    )


@mcp.tool()
def delete_location(
    campaign_id: str,
    location_id_or_name: str,
) -> dict[str, Any]:
    """Usuń lokację z kampanii na podstawie jej id lub nazwy.

    - campaign_id: id kampanii
    - location_id_or_name: id lub nazwa lokacji do usunięcia

    Skutek uboczny: usunięcie lokacji z `campaign.locations` oraz wpis typu
    \"mutate\" (op=\"delete_location\").
    """
    return mutation_service.mutate(
        campaign_id=campaign_id,
        op="delete_location",
        value=location_id_or_name,
    )


@mcp.tool()
def list_factions(campaign_id: str) -> list[dict[str, Any]]:
    """Zwróć listę frakcji kampanii (`campaign.factions`)."""
    data = storage.load_campaign(campaign_id)
    return list(data.get("factions") or [])


@mcp.tool()
def upsert_faction(
    campaign_id: str,
    faction: dict[str, Any],
) -> dict[str, Any]:
    """Dodaj lub zaktualizuj frakcję w kampanii.

    - campaign_id: id kampanii
    - faction: obiekt JSON z polami np. id, name, description, rep

    Jeśli frakcja z podanym id istnieje, pola name/description/rep zostaną
    zaktualizowane (rep ustawione na podaną wartość). Jeśli nie istnieje,
    powstanie nowa frakcja.
    """
    return mutation_service.mutate(
        campaign_id=campaign_id,
        op="faction_upsert",
        value=faction,
    )


@mcp.tool()
def faction_rep_add(
    campaign_id: str,
    faction_id: str,
    delta: int,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Zwiększ/zmniejsz reputację frakcji w kampanii.

    - campaign_id: id kampanii
    - faction_id: id frakcji (np. \"ministerstwo-rt\")
    - delta: zmiana reputacji (może być ujemna)
    - name: opcjonalna nazwa frakcji; jeśli frakcja nie istnieje, zostanie utworzona

    Skutek uboczny: aktualizacja `campaign.factions` oraz wpis typu \"mutate\"
    (op=\"faction_rep_add\").
    """
    payload = {
        "id": faction_id,
        "delta": delta,
    }
    if name is not None:
        payload["name"] = name
    return mutation_service.mutate(
        campaign_id=campaign_id,
        op="faction_rep_add",
        value=payload,
    )


@mcp.tool()
def roll_dice(
    expr: str,
    campaign_id: Optional[str] = None,
    note: Optional[str] = None,
    log: bool = True,
) -> dict[str, Any]:
    """Wykonaj rzut kośćmi w notacji np. \"1d20+5\".

    - expr: wyrażenie kościane (np. \"2d6+3\", \"1d20+5\")
    - campaign_id: opcjonalne id kampanii, jeśli chcesz zalogować wynik w historii
    - note: dodatkowy opis (np. \"atak Tima\"), dołączany do tekstu w logu
    - log: jeśli True i podano campaign_id, wynik trafia do loga (type=\"history\")
    """
    try:
        roll = d20.roll(expr)
    except Exception as e:
        raise ValueError(f"invalid dice expression {expr!r}: {e}")

    total = int(roll.total)
    rendered = str(roll)

    result: dict[str, Any] = {
        "expression": expr,
        "total": total,
        "rendered": rendered,
    }

    if log and campaign_id:
        text_parts = [f"Rzut {expr} = {total} ({rendered})"]
        if note:
            text_parts.append(f"- {note}")
        storage.log_event(
            {
                "type": "history",
                "campaign_id": campaign_id,
                "char_id": None,
                "amount": None,
                "text": " ".join(text_parts),
                "value": {
                    "expr": expr,
                    "total": total,
                    "rendered": rendered,
                },
            }
        )
        result["logged"] = True
    else:
        result["logged"] = False

    return result


@mcp.tool()
def world_find_route(
    campaign_id: str,
    from_id: Optional[str] = None,
    to_id: Optional[str] = None,
) -> dict[str, Any]:
    """Znajdź trasę między lokacjami kampanii.

    - campaign_id: id kampanii
    - from_id: id lokacji startowej (domyślnie current_location_id lub lokacja kampanii)
    - to_id: id lokacji docelowej (wymagane)

    Korzysta z campaign.locations (id, name, type, tags, description)
    oraz opcjonalnego campaign.connections: lista obiektów
    {\"from\", \"to\", \"distance\"?}. Jeśli connections brak, zakłada bezpośrednie
    przejście między from_id i to_id.
    """
    data = storage.load_campaign(campaign_id)
    locations = data.get("locations") or []
    if not locations:
        raise ValueError("campaign has no locations defined")

    id_to_loc: dict[str, dict[str, Any]] = {}
    for loc in locations:
        lid = str(loc.get("id") or "")
        if not lid:
            continue
        id_to_loc[lid] = loc

    if not id_to_loc:
        raise ValueError("no valid locations with 'id' in campaign")

    current_id = str(data.get("current_location_id") or "").strip()
    if not current_id:
        current_name = str(data.get("location") or "").strip()
        for lid, loc in id_to_loc.items():
            if str(loc.get("name") or "").strip() == current_name:
                current_id = lid
                break
        if not current_id:
            current_id = next(iter(id_to_loc.keys()))

    start_id = from_id or current_id
    if not start_id:
        raise ValueError("from_id could not be determined")
    if to_id is None:
        raise ValueError("to_id is required")
    start_id = str(start_id)
    to_id = str(to_id)

    if start_id not in id_to_loc:
        raise ValueError(f"unknown from_id: {start_id!r}")
    if to_id not in id_to_loc:
        raise ValueError(f"unknown to_id: {to_id!r}")

    g = nx.Graph()
    for lid in id_to_loc.keys():
        g.add_node(lid)

    connections = data.get("connections") or []
    if connections:
        for conn in connections:
            a = str(conn.get("from") or "")
            b = str(conn.get("to") or "")
            if not a or not b:
                continue
            if a not in id_to_loc or b not in id_to_loc:
                continue
            distance = conn.get("distance")
            try:
                weight = float(distance) if distance is not None else 1.0
            except Exception:
                weight = 1.0
            g.add_edge(a, b, weight=weight, meta=conn)
    else:
        g.add_edge(start_id, to_id, weight=1.0, meta=None)

    try:
        path_ids = nx.shortest_path(g, start_id, to_id, weight="weight")
        total_weight = nx.path_weight(g, path_ids, weight="weight")
    except Exception as e:
        raise ValueError(f"cannot find route from {start_id!r} to {to_id!r}: {e}")

    path_locs = [
        {
            "id": lid,
            "name": id_to_loc[lid].get("name") or lid,
            "type": id_to_loc[lid].get("type"),
            "tags": id_to_loc[lid].get("tags"),
        }
        for lid in path_ids
    ]

    edges: List[dict[str, Any]] = []
    for a, b in zip(path_ids, path_ids[1:]):
        data_edge = g.get_edge_data(a, b) or {}
        meta = data_edge.get("meta") or {}
        edges.append(
            {
                "from": a,
                "to": b,
                "distance": data_edge.get("weight"),
                "meta": meta,
            }
        )

    return {
        "campaign_id": campaign_id,
        "from_id": start_id,
        "to_id": to_id,
        "path": path_locs,
        "total_distance": total_weight,
        "edges": edges,
    }


@mcp.tool()
def mutate(
    campaign_id: str,
    op: str,
    char_id: Optional[str] = None,
    amount: Optional[int] = None,
    text: Optional[str] = None,
    value: Optional[Any] = None,
) -> dict[str, Any]:
    """Modyfikacja stanu kampanii / postaci / świata.

    Parametr `op` określa rodzaj operacji. Najważniejsze:

    - postacie: `gold_add`, `hp_add`, `xp_add`, `note_append`, `char_note_add`,
      `campaign_note_add`, `alignment_set`, `persona_set`,
      `inventory_add`, `inventory_remove`
    - czas / miejsce: `day_add`, `day_set`, `location_set`
    - lokacje:
      - `upsert_location` – dodanie lub aktualizacja lokacji na podstawie
        `value` (JSON z polami np. `id`, `name`, `type`, `tags`, `description`)
      - `delete_location` – usunięcie lokacji na podstawie id lub nazwy
    - kampania: `update_campaign` – twarda edycja pól kampanii (name/notes/day/location/current_location_id)
    - świat / questy / frakcje: `world_flag_set`, `quest_update`, `faction_rep_add`
    - usuwanie postaci: `delete_character` (wymaga `char_id`)
    - sam log historii: `history_log` (tylko wpis do loga, bez modyfikacji kampanii)

    Pełna implementacja i walidacja znajduje się w rpg_ledger.mutation_service.mutate.
    """
    return mutation_service.mutate(
        campaign_id=campaign_id,
        op=op,
        char_id=char_id,
        amount=amount,
        text=text,
        value=value,
    )


@dev_mcp.tool()
def dev_todo(
    summary: str,
    details: Optional[str] = None,
    tags: Optional[List[str]] = None,
    campaign_id: Optional[str] = None,
    char_id: Optional[str] = None,
) -> dict[str, Any]:
    """Zapisz TODO dla dalszego rozwoju legera.

    Użyj tego narzędzia z poziomu MG/AI, aby odnotować brakującą funkcjonalność
    (np. nowy typ mutacji, raport, integrację itp.).

    Zapis trafia do osobnego logu TODO (dev-todos.jsonl) z typem "todo",
    odczytywanego przez Dev MCP oraz /api/dev-todos.
    """
    storage.log_event(
        {
            "type": "todo",
            "summary": summary,
            "details": details,
            "tags": tags or [],
            "campaign_id": campaign_id,
            "char_id": char_id,
            "done": False,
            "comment": "",
        },
        file=storage.DEV_TODO_FILE,
    )
    return {"ok": True}


def _read_dev_todos(limit: int = 100) -> list[dict[str, Any]]:
    return storage.read_dev_todos(limit=limit)


@dev_mcp.tool()
def dev_get_logs(
    limit: int = 100,
    event_type: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Zwróć ostatnie wpisy z logów.

    - jeśli podano campaign_id, czyta tylko log tej kampanii,
    - w przeciwnym razie czyta globalny logs.jsonl.
    """
    return storage.read_logs(limit=limit, event_type=event_type, campaign_id=campaign_id)


@dev_mcp.tool()
def dev_get_todos(limit: int = 50) -> list[dict[str, Any]]:
    """Zwróć ostatnie TODO zapisane przez dev_todo."""
    return _read_dev_todos(limit=limit)


@mcp.tool()
def spawn_npc_group(
    campaign_id: str,
    template_id: str,
    count: int = 1,
    group_id: Optional[str] = None,
) -> dict[str, Any]:
    """Wygeneruj grupę NPC na podstawie szablonu z data/npc_templates.

    - campaign_id: id kampanii
    - template_id: id szablonu (np. \"bandit-thug\")
    - count: ilu NPC wygenerować (domyślnie 1)
    - group_id: opcjonalne id grupy (npc_group_id); domyślnie template_id + timestamp
    """
    if count <= 0:
        raise ValueError("count must be > 0")

    data = storage.load_campaign(campaign_id)
    template = storage.load_npc_template(template_id)

    data, group_id, new_ids = npc_factory.spawn_group(
        campaign=data,
        template=template,
        template_id=template_id,
        count=count,
        group_id=group_id,
    )

    storage.save_campaign(campaign_id, data)
    storage.log_event(
        {
            "type": "history",
            "campaign_id": campaign_id,
            "char_id": None,
            "amount": None,
            "text": f"dev_spawn_npc_group template={template_id} group_id={group_id} count={count}",
            "value": {
                "template_id": template_id,
                "group_id": group_id,
                "npc_ids": new_ids,
            },
        }
    )

    return {
        "ok": True,
        "campaign_id": campaign_id,
        "template_id": template_id,
        "group_id": group_id,
        "npc_ids": new_ids,
    }


@dev_mcp.tool()
def dev_request_restart(target: str = "stack") -> dict[str, Any]:
    """Zgłoś prośbę o restart stacka / serwisów.

    NIE wykonuje restartu samodzielnie – tylko zapisuje zdarzenie
    type == "dev_restart_request" w logs.jsonl.

    target: "stack", "gameserver", "mcp".
    """
    allowed = {"stack", "gameserver", "mcp"}
    if target not in allowed:
        raise ValueError(f"target must be one of {sorted(allowed)}")
    payload = {
        "type": "dev_restart_request",
        "target": target,
    }
    storage.log_event(payload)
    return {"ok": True, "requested": target}


@dev_mcp.tool()
def dev_get_ci_status() -> dict[str, Any]:
    """Zwróć status deployu/CI z pliku ci-status.json."""
    if not storage.CI_STATUS_FILE.exists():
        return {"status": "unknown"}
    try:
        with storage.CI_STATUS_FILE.open("r", encoding="utf-8") as f:
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
    """Czekaj aż CI/deploy osiągnie zadany status."""
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


@mcp.tool()
def save_campaign_snapshot(campaign_id: str, slot: str = "initial") -> dict[str, Any]:
    """Zapisz migawkę kampanii do pliku data/_snapshots/{campaign_id}.{slot}.json.

    Skutek uboczny: zapis pliku snapshotu oraz wpis w logu kampanii (type=\"history\").
    """
    data = storage.load_campaign(campaign_id)
    storage.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = storage.snapshot_path(campaign_id, slot)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    storage.log_event(
        {
            "type": "history",
            "campaign_id": campaign_id,
            "char_id": None,
            "amount": None,
            "text": f"save_campaign_snapshot slot={slot}",
            "value": {"slot": slot, "path": str(path)},
        }
    )
    return {"ok": True, "campaign_id": campaign_id, "slot": slot, "path": str(path)}


@mcp.tool()
def restore_campaign_snapshot(campaign_id: str, slot: str = "initial") -> dict[str, Any]:
    """Przywróć kampanię z wcześniej zapisanego snapshotu.

    Skutek uboczny: nadpisuje plik kampanii oraz dopisuje wpis do logu (type=\"history\").
    """
    path = storage.snapshot_path(campaign_id, slot)
    if not path.exists():
        raise FileNotFoundError(f"snapshot {campaign_id!r} slot {slot!r} not found")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    storage.save_campaign(campaign_id, data)
    storage.log_event(
        {
            "type": "history",
            "campaign_id": campaign_id,
            "char_id": None,
            "amount": None,
            "text": f"restore_campaign_snapshot slot={slot}",
            "value": {"slot": slot, "path": str(path)},
        }
    )
    return data


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


@app.post("/api/campaigns/create")
async def api_create_campaign(payload: dict[str, Any]) -> dict[str, Any]:
    """HTTP API do tworzenia kampanii (wrapper na MCP create_campaign)."""
    return create_campaign(**payload)


@app.get("/api/factions/{campaign_id}")
async def api_factions(campaign_id: str) -> list[dict[str, Any]]:
    """HTTP API: zwróć frakcje kampanii (wrapper na list_factions)."""
    return list_factions(campaign_id)


@app.post("/api/factions/{campaign_id}/rep")
async def api_faction_rep(
    campaign_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """HTTP API: zmień reputację frakcji (wrapper na faction_rep_add)."""
    faction_id = str(payload.get("faction_id") or "").strip()
    if not faction_id:
        raise ValueError("faction_id is required")
    try:
        delta = int(payload.get("delta"))
    except Exception:
        raise ValueError("delta must be an integer")
    name = payload.get("name")
    return faction_rep_add(
        campaign_id=campaign_id,
        faction_id=faction_id,
        delta=delta,
        name=name,
    )


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

    import json as _json

    if not storage.DEV_TODO_FILE.exists():
        return {"ok": False, "error": "dev todos file not found"}

    entries: list[dict[str, Any]] = []
    with storage.DEV_TODO_FILE.open("r", encoding="utf-8", errors="ignore") as f:
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

    storage.write_dev_todos(entries)

    return {"ok": True}


@app.get("/api/campaigns/{campaign_id}")
async def api_campaign(campaign_id: str) -> dict[str, Any]:
    return storage.load_campaign(campaign_id)


@app.get("/api/logs")
async def api_logs(
    limit: int = 100,
    campaign_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    return dev_get_logs(limit=limit, campaign_id=campaign_id)


@app.get("/api/dev-todos")
async def api_dev_todos(limit: int = 100) -> list[dict[str, Any]]:
    return _read_dev_todos(limit=limit)
