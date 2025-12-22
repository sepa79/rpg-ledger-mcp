from __future__ import annotations

import json
from typing import Any, Optional, Dict

from . import storage
from . import npc_factory  # kept for potential future reuse


def mutate(
    campaign_id: str,
    op: str,
    char_id: Optional[str] = None,
    amount: Optional[int] = None,
    text: Optional[str] = None,
    value: Optional[Any] = None,
) -> Dict[str, Any]:
    """Modyfikacja stanu kampanii / postaci.

    Zachowuje dokładnie tę samą semantykę co pierwotne mutate z app.py.
    """
    data = storage.load_campaign(campaign_id)

    character: Optional[Dict[str, Any]] = None
    if char_id is not None:
        # lokalna wersja _find_character, żeby nie wiązać się z app.py
        chars = data.get("characters") or []
        for ch in chars:
            if ch.get("id") == char_id:
                character = ch
                break
        if character is None:
            raise KeyError(f"Character {char_id!r} not found in campaign {data.get('id')}")

    def require_amount() -> int:
        if amount is None:
            raise ValueError("amount is required for this operation")
        return int(amount)

    # Parsowanie value jako JSON (jesli to ma sens)
    if value is None:
        parsed_value: Any = None
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

    elif op == "alignment_set":
        if character is None:
            raise ValueError("char_id is required for alignment_set")
        if value is None and parsed_value is None:
            raise ValueError("value or parsed_value is required for alignment_set")
        if isinstance(parsed_value, dict):
            alignment = str(parsed_value.get("alignment") or "")
        else:
            alignment = str(value if value is not None else parsed_value)
        alignment = alignment.strip()
        if not alignment:
            raise ValueError("alignment cannot be empty")
        character["alignment"] = alignment

    elif op == "persona_set":
        if character is None:
            raise ValueError("char_id is required for persona_set")
        if not text:
            raise ValueError("text is required for persona_set")
        character["persona"] = text

    # ----------------- Czas / miejsce -----------------

    elif op == "day_add":
        delta = require_amount()
        current = int(data.get("day") or 0)
        data["day"] = current + delta

    elif op == "day_set":
        new_day = require_amount()
        data["day"] = new_day

    elif op == "location_set":
        if value is None and parsed_value is None:
            raise ValueError("value is required for location_set")

        target_id: str
        label: str
        if isinstance(parsed_value, dict):
            target_id = str(parsed_value.get("id") or parsed_value.get("name") or "")
            if not target_id:
                raise ValueError("location_set value object must have 'id' or 'name'")
            label = str(parsed_value.get("name") or target_id)
        else:
            label = str(value if value is not None else parsed_value)
            target_id = label
            # Jeśli istnieje już lokacja o takiej nazwie, użyj jej id,
            # zamiast tworzyć duplikat z id równym nazwie.
            existing_locs = data.get("locations") or []
            for loc in existing_locs:
                name = str(loc.get("name") or "").strip()
                lid = str(loc.get("id") or "").strip()
                if name and name == label.strip() and lid:
                    target_id = lid
                    break

        data["location"] = label
        data["current_location_id"] = target_id

        locations = data.setdefault("locations", [])
        existing = None
        for loc in locations:
            if loc.get("id") == target_id:
                existing = loc
                break
        if existing is None:
            locations.append(
                {
                    "id": target_id,
                    "name": label,
                    "type": "place",
                    "tags": [],
                    "description": "",
                }
            )

    elif op == "upsert_location":
        if not isinstance(parsed_value, dict):
            raise ValueError("upsert_location requires JSON object in 'value'")
        raw_id = str(parsed_value.get("id") or "").strip()
        raw_name = str(parsed_value.get("name") or "").strip()
        if not raw_id and not raw_name:
            raise ValueError("upsert_location requires at least 'id' or 'name' in value")

        locations = data.setdefault("locations", [])
        target: Optional[Dict[str, Any]] = None

        if raw_id:
            for loc in locations:
                if str(loc.get("id") or "").strip() == raw_id:
                    target = loc
                    break
        if target is None and raw_name:
            for loc in locations:
                if str(loc.get("name") or "").strip() == raw_name:
                    target = loc
                    break

        if target is None:
            base_id = raw_id or raw_name or "place"
            safe_id = "".join(c for c in base_id if c.isalnum() or c in "-_") or "place"
            target = {"id": safe_id}
            locations.append(target)

        if raw_name:
            target["name"] = raw_name
        if "type" in parsed_value and parsed_value["type"] is not None:
            target["type"] = parsed_value["type"]
        if "description" in parsed_value and parsed_value["description"] is not None:
            target["description"] = parsed_value["description"]
        if "tags" in parsed_value and parsed_value["tags"] is not None:
            target["tags"] = list(parsed_value["tags"])

    elif op == "delete_location":
        if parsed_value is None and value is None:
            raise ValueError("delete_location requires 'value' with id or name")

        loc_id: Optional[str] = None
        loc_name: Optional[str] = None
        if isinstance(parsed_value, dict):
            loc_id = str(parsed_value.get("id") or "").strip()
            loc_name = str(parsed_value.get("name") or "").strip()
        elif isinstance(parsed_value, str):
            loc_id = parsed_value.strip()
        else:
            raise ValueError("delete_location requires string or object in 'value'")

        if not loc_id and not loc_name:
            raise ValueError("delete_location requires 'id' or 'name'")

        locations = data.get("locations") or []
        remaining: list[Dict[str, Any]] = []
        removed: list[Dict[str, Any]] = []
        for loc in locations:
            lid = str(loc.get("id") or "").strip()
            lname = str(loc.get("name") or "").strip()
            if (loc_id and lid == loc_id) or (loc_name and lname == loc_name):
                removed.append(loc)
            else:
                remaining.append(loc)

        if not removed:
            ident = loc_id or loc_name or "?"
            raise KeyError(f"Location {ident!r} not found in campaign {data.get('id')}")

        data["locations"] = remaining

        # Jeśli usunięta lokacja była aktualną, wyczyść wskaźniki.
        cur_id = str(data.get("current_location_id") or "").strip()
        cur_name = str(data.get("location") or "").strip()
        for loc in removed:
            lid = str(loc.get("id") or "").strip()
            lname = str(loc.get("name") or "").strip()
            if cur_id and lid == cur_id:
                data["current_location_id"] = ""
            if cur_name and lname == cur_name:
                data["location"] = ""

    # ----------------- Ekwipunek -----------------

    elif op == "inventory_add":
        if character is None:
            raise ValueError("char_id is required for inventory_add")
        if not isinstance(parsed_value, dict) or "id" not in parsed_value:
            raise ValueError("inventory_add requires JSON in 'value' with at least 'id'")
        item_id = str(parsed_value["id"])
        name = str(parsed_value.get("name") or item_id)
        qty_raw = parsed_value.get("qty", 1)
        qty = int(qty_raw)
        if qty <= 0:
            raise ValueError("qty for inventory_add must be > 0")
        inventory = character.setdefault("inventory", [])
        for it in inventory:
            if it.get("id") == item_id:
                it["qty"] = int(it.get("qty") or 0) + qty
                break
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
        remaining: list[Dict[str, Any]] = []
        for it in inventory:
            if it.get("id") != item_id:
                remaining.append(it)
                continue
            current_qty = int(it.get("qty") or 0)
            new_qty = current_qty - qty
            if new_qty > 0:
                it["qty"] = new_qty
                remaining.append(it)
        character["inventory"] = remaining

    # ----------------- Stan swiata / questy / frakcje -----------------

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

    elif op == "faction_upsert":
        if not isinstance(parsed_value, dict):
            raise ValueError("faction_upsert requires JSON object in 'value'")
        raw_id = str(parsed_value.get("id") or "").strip()
        raw_name = str(parsed_value.get("name") or "").strip()
        if not raw_id and not raw_name:
            raise ValueError("faction_upsert requires at least 'id' or 'name'")

        factions = data.setdefault("factions", [])
        target: Optional[Dict[str, Any]] = None
        if raw_id:
            for f in factions:
                if str(f.get("id") or "").strip() == raw_id:
                    target = f
                    break
        if target is None and raw_name:
            for f in factions:
                if str(f.get("name") or "").strip() == raw_name:
                    target = f
                    break

        if target is None:
            base_id = raw_id or raw_name or "faction"
            safe_id = "".join(c for c in base_id if c.isalnum() or c in "-_") or "faction"
            target = {"id": safe_id, "rep": 0}
            factions.append(target)

        if raw_name:
            target["name"] = raw_name
        if "description" in parsed_value and parsed_value["description"] is not None:
            target["description"] = parsed_value["description"]
        if "rep" in parsed_value and parsed_value["rep"] is not None:
            try:
                target["rep"] = int(parsed_value["rep"])
            except Exception:
                raise ValueError("faction_upsert.rep must be an integer if provided")

    # ----------------- Kampania / postacie (twarda edycja) -----------------

    elif op == "update_campaign":
        if not isinstance(parsed_value, dict):
            raise ValueError("update_campaign requires JSON object in 'value'")
        if "name" in parsed_value and parsed_value["name"] is not None:
            data["name"] = parsed_value["name"]
        if "notes" in parsed_value:
            val = parsed_value["notes"]
            if val is not None:
                data["notes"] = val
        if "day" in parsed_value and parsed_value["day"] is not None:
            try:
                data["day"] = int(parsed_value["day"])
            except Exception:
                raise ValueError("update_campaign.day must be an integer")
        if "location" in parsed_value and parsed_value["location"] is not None:
            data["location"] = parsed_value["location"]
        if "current_location_id" in parsed_value and parsed_value["current_location_id"] is not None:
            data["current_location_id"] = parsed_value["current_location_id"]

    elif op == "delete_character":
        if char_id is None:
            raise ValueError("char_id is required for delete_character")
        chars = data.get("characters") or []
        remaining: list[Dict[str, Any]] = []
        found = False
        for ch in chars:
            if ch.get("id") == char_id:
                found = True
                continue
            remaining.append(ch)
        if not found:
            raise KeyError(f"Character {char_id!r} not found in campaign {data.get('id')}")
        data["characters"] = remaining

    # ----------------- Tylko log historii -----------------

    elif op == "history_log":
        storage.log_event(
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
    storage.save_campaign(campaign_id, data)

    storage.log_event(
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
