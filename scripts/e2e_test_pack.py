#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple


BASE_URL = "http://localhost:8000"
CAMPAIGN_ID = "kampania-test"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _http(method: str, path: str, body: Dict[str, Any] | None = None) -> Tuple[int, Any]:
    url = BASE_URL + path
    data = None
    headers: Dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read().decode("utf-8")
        return resp.getcode(), json.loads(raw)


def wait_for_server(timeout_seconds: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            code, _ = _http("GET", "/api/campaigns")
            if code == 200:
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            time.sleep(1)
    return False


def reset_campaign_file() -> None:
    """Przywróć plik kampanii testowej do stanu początkowego z szablonu na dysku.

    Operuje tylko na plikach w ./data – nie dotyka logów jsonl.
    """
    template = REPO_ROOT / "data" / "kampania-test.template.json"
    target = REPO_ROOT / "data" / "kampania-test.json"
    if not template.exists():
        return
    try:
        text = template.read_text(encoding="utf-8")
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"[E2E] WARN: nie udało się odtworzyć kampanii testowej z szablonu: {exc}", file=sys.stderr)


def find_char(campaign: Dict[str, Any], char_id: str) -> Dict[str, Any]:
    for ch in campaign.get("characters") or []:
        if ch.get("id") == char_id:
            return ch
    raise KeyError(f"Character {char_id!r} not found in campaign {campaign.get('id')!r}")


def main() -> int:
    print(f"[E2E] Start – expecting server at {BASE_URL}")

    # Zawsze odtwarzamy kampanię testową przed testem,
    # żeby zaczynać od znanego stanu.
    reset_campaign_file()

    if not wait_for_server():
        print(
            "[E2E] ERROR: serwer nie odpowiada na /api/campaigns.\n"
            "Upewnij się, że stack działa (np. `docker compose up -d`).",
            file=sys.stderr,
        )
        return 1

    # 1) Lista kampanii i obecność kampanii testowej
    code, campaigns = _http("GET", "/api/campaigns")
    if code != 200 or not isinstance(campaigns, list):
        print("[E2E] ERROR: /api/campaigns nie zwróciło poprawnej listy.", file=sys.stderr)
        return 1

    ids = {c.get("id") for c in campaigns}
    if CAMPAIGN_ID not in ids:
        print(
            f"[E2E] ERROR: kampania testowa {CAMPAIGN_ID!r} nie istnieje "
            f"(ids={sorted(ids)!r}).",
            file=sys.stderr,
        )
        return 1
    print("[E2E] OK: kampania testowa widoczna w /api/campaigns.")

    # 2) Pobranie kampanii testowej i stan początkowy
    code, camp = _http("GET", f"/api/campaigns/{CAMPAIGN_ID}")
    if code != 200 or not isinstance(camp, dict):
        print("[E2E] ERROR: /api/campaigns/kampania-test nie zwróciło słownika.", file=sys.stderr)
        return 1

    try:
        war = find_char(camp, "test-warrior")
        mage = find_char(camp, "test-mage")
    except KeyError as e:
        print(f"[E2E] ERROR: {e}", file=sys.stderr)
        return 1

    hp_before = int(war.get("hp") or 0)
    gold_before = int(mage.get("gold") or 0)
    location_before = camp.get("location")
    print(
        f"[E2E] Stan początkowy: hp_war={hp_before}, "
        f"gold_mage={gold_before}, location={location_before!r}"
    )

    # 3) Mutacje na kampanii testowej (hp, gold, lokacja)
    # hp_add na wojowniku
    code, camp = _http(
        "POST",
        "/api/mutate",
        {
            "campaign_id": CAMPAIGN_ID,
            "op": "hp_add",
            "char_id": "test-warrior",
            "amount": -3,
            "text": "E2E hp_add",
        },
    )
    if code != 200:
        print("[E2E] ERROR: mutate hp_add zwróciło status != 200.", file=sys.stderr)
        return 1
    war_after = find_char(camp, "test-warrior")
    hp_after = int(war_after.get("hp") or 0)
    if hp_after != hp_before - 3:
        print(
            f"[E2E] ERROR: hp_add nie zadziałało: hp_before={hp_before}, hp_after={hp_after}.",
            file=sys.stderr,
        )
        return 1
    print("[E2E] OK: mutate hp_add na test-warrior.")

    # gold_add na magini
    code, camp = _http(
        "POST",
        "/api/mutate",
        {
            "campaign_id": CAMPAIGN_ID,
            "op": "gold_add",
            "char_id": "test-mage",
            "amount": 7,
            "text": "E2E gold_add",
        },
    )
    if code != 200:
        print("[E2E] ERROR: mutate gold_add zwróciło status != 200.", file=sys.stderr)
        return 1
    mage_after = find_char(camp, "test-mage")
    gold_after = int(mage_after.get("gold") or 0)
    if gold_after != gold_before + 7:
        print(
            f"[E2E] ERROR: gold_add nie zadziałało: gold_before={gold_before}, gold_after={gold_after}.",
            file=sys.stderr,
        )
        return 1
    print("[E2E] OK: mutate gold_add na test-mage.")

    # location_set na kampanii
    code, camp = _http(
        "POST",
        "/api/mutate",
        {
            "campaign_id": CAMPAIGN_ID,
            "op": "location_set",
            "value": "Las Testowy",
            "text": "E2E location_set",
        },
    )
    if code != 200:
        print("[E2E] ERROR: mutate location_set zwróciło status != 200.", file=sys.stderr)
        return 1
    location_after = camp.get("location")
    if location_after != "Las Testowy":
        print(
            f"[E2E] ERROR: location_set nie zadziałało: location_after={location_after!r}.",
            file=sys.stderr,
        )
        return 1
    print("[E2E] OK: mutate location_set na kampanii testowej.")

    # 4) Weryfikacja, że mutacje trafiły do loga
    code, logs = _http("GET", f"/api/logs?campaign_id={CAMPAIGN_ID}")
    if code != 200 or not isinstance(logs, list):
        print("[E2E] ERROR: /api/logs nie zwróciło listy.", file=sys.stderr)
        return 1

    markers = {"hp_add": False, "gold_add": False, "location_set": False}
    for entry in logs:
        if entry.get("campaign_id") != CAMPAIGN_ID:
            continue
        if entry.get("type") != "mutate":
            continue
        if entry.get("text") == "E2E hp_add" and entry.get("op") == "hp_add":
            markers["hp_add"] = True
        elif entry.get("text") == "E2E gold_add" and entry.get("op") == "gold_add":
            markers["gold_add"] = True
        elif entry.get("text") == "E2E location_set" and entry.get("op") == "location_set":
            markers["location_set"] = True

    missing: List[str] = [name for name, ok in markers.items() if not ok]
    if missing:
        print(
            f"[E2E] ERROR: w logach brakuje wpisów mutacji dla kampanii testowej: {missing}.",
            file=sys.stderr,
        )
        return 1

    print("[E2E] OK: wszystkie testowe mutacje obecne w logs.jsonl.")

    # Po udanym teście przywracamy kampanię do stanu początkowego.
    reset_campaign_file()
    print("[E2E] Kampania testowa przywrócona z szablonu.")
    print("[E2E] SUKCES – test pack dla kampanii testowej przeszedł pomyślnie.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
