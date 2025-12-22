from __future__ import annotations

import time
import random
from typing import Any, Dict, List, Tuple, Set, Optional

import d20


def _roll_hp(template: Dict[str, Any]) -> int:
    hp_roll = template.get("hp_roll")
    base_hp = template.get("hp") or template.get("base_hp")
    if isinstance(hp_roll, str):
        try:
            return int(d20.roll(hp_roll).total)
        except Exception:
            pass
    if isinstance(base_hp, (int, float)):
        return int(base_hp)
    return int(d20.roll("1d8").total)


def _roll_gold(template: Dict[str, Any]) -> int:
    gold_tpl = template.get("gold")
    if isinstance(gold_tpl, (int, float)):
        return int(gold_tpl)
    if isinstance(gold_tpl, dict):
        gmin = int(gold_tpl.get("min", 0))
        gmax = int(gold_tpl.get("max", gmin))
        if gmax < gmin:
            gmax = gmin
        return random.randint(gmin, gmax)
    return 0


def _normalize_base_id(template_id: str, template: Dict[str, Any]) -> str:
    base_raw = str(template.get("id") or template_id)
    base = "".join(c for c in base_raw if c.isalnum() or c in "-_")
    return base or "npc"


def spawn_group(
    campaign: Dict[str, Any],
    template: Dict[str, Any],
    template_id: str,
    count: int = 1,
    group_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    """Wygeneruj grupę NPC na podstawie szablonu.

    Zwraca zaktualizowaną kampanię, npc_group_id i listę id nowych NPC.
    Nie wykonuje I/O – tylko modyfikuje przekazany słownik kampanii.
    """
    if count <= 0:
        raise ValueError("count must be > 0")

    characters: List[Dict[str, Any]] = campaign.setdefault("characters", [])
    existing_ids: Set[str] = {str(c.get("id")) for c in characters if c.get("id")}

    base_id = _normalize_base_id(template_id, template)
    if not group_id:
        group_id = f"{base_id}-grp-{int(time.time())}"

    new_ids: List[str] = []

    for i in range(count):
        suffix = i + 1
        while True:
            candidate = f"{base_id}-{suffix}"
            if candidate not in existing_ids:
                existing_ids.add(candidate)
                break
            suffix += 1

        name = str(template.get("name") or "NPC")
        display_name = f"{name} #{suffix}" if count > 1 else name

        npc: Dict[str, Any] = {
            "id": candidate,
            "name": display_name,
            "class": template.get("class"),
            "level": template.get("level", 1),
            "xp": template.get("xp", 0),
            "hp": _roll_hp(template),
            "alignment": template.get("alignment"),
            "persona": template.get("persona"),
            "stats": template.get("stats", {}),
            "gold": _roll_gold(template),
            "inventory": [dict(item) for item in (template.get("inventory") or [])],
            "is_npc": True,
            "npc_group_id": group_id,
            "tags": (template.get("tags") or []) + ["npc"],
        }

        characters.append(npc)
        new_ids.append(candidate)

    return campaign, group_id, new_ids

