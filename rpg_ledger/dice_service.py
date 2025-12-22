from __future__ import annotations

from typing import Any, Optional, Dict

import d20

from . import storage


def roll_dice(
    expr: str,
    campaign_id: Optional[str] = None,
    note: Optional[str] = None,
    log: bool = True,
) -> Dict[str, Any]:
    """Logika rzutu kośćmi, używana przez MCP i inne serwisy."""
    try:
        roll = d20.roll(expr)
    except Exception as e:
        raise ValueError(f"invalid dice expression {expr!r}: {e}")

    total = int(roll.total)
    rendered = str(roll)

    result: Dict[str, Any] = {
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

