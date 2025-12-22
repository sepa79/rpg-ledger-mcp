from __future__ import annotations

import json
import datetime
from pathlib import Path
from typing import Any, List, Optional, Dict

# Bazowe katalogi / ścieżki
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = Path("/app/logs-dir")
LOG_FILE = LOG_DIR / "logs.jsonl"
DEV_TODO_FILE = LOG_DIR / "dev-todos.jsonl"
CI_STATUS_FILE = LOG_DIR / "ci-status.json"
SNAPSHOT_DIR = DATA_DIR / "_snapshots"
NPC_TEMPLATES_DIR = DATA_DIR / "npc_templates"


def campaign_path(campaign_id: str) -> Path:
  safe = "".join(c for c in campaign_id if c.isalnum() or c in "-_")
  return DATA_DIR / f"{safe}.json"


def load_campaign(campaign_id: str) -> dict[str, Any]:
  path = campaign_path(campaign_id)
  if not path.exists():
    raise FileNotFoundError(f"Campaign {campaign_id!r} not found")
  with path.open("r", encoding="utf-8") as f:
    return json.load(f)


def save_campaign(campaign_id: str, data: dict[str, Any]) -> None:
  path = campaign_path(campaign_id)
  DATA_DIR.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)


def snapshot_path(campaign_id: str, slot: str) -> Path:
  safe_id = "".join(c for c in campaign_id if c.isalnum() or c in "-_")
  safe_slot = "".join(c for c in slot if c.isalnum() or c in "-_")
  return SNAPSHOT_DIR / f"{safe_id}.{safe_slot}.json"


def log_event(event: dict[str, Any], *, file: Path | None = None) -> None:
  """Zapisz zdarzenie do loga.

  Domyślnie zapisuje do globalnego logs.jsonl (LOG_FILE).
  DEV_TODO i inne specjalne logi mogą podać własny plik przez parametr file.
  """
  file = file or LOG_FILE
  event = dict(event)
  event.setdefault(
      "ts",
      datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
  )

  def _append(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
      f.write(json.dumps(event, ensure_ascii=False) + "\n")

  _append(file)


def read_dev_todos(limit: int = 100) -> list[dict[str, Any]]:
  if not DEV_TODO_FILE.exists():
    return []
  entries: list[dict[str, Any]] = []
  with DEV_TODO_FILE.open("r", encoding="utf-8") as f:
    for line in f:
      line = line.strip()
      if not line:
        continue
      try:
        obj = json.loads(line)
      except Exception:
        continue
      entries.append(obj)
  entries.sort(key=lambda e: e.get("ts", ""))
  if limit and limit > 0:
    entries = entries[-limit:]
  entries.reverse()
  return entries


def read_logs(
    limit: int = 100,
    event_type: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """Odczytaj logi z globalnego pliku logs.jsonl, opcjonalnie filtrując po typie i kampanii.

  Zgodnie z zasadą, że logs/logs.jsonl jest źródłem prawdy, per‑kampanijne pliki
  (jeśli istnieją) są traktowane tylko jako kopia pomocnicza – do odczytu używamy LOG_FILE.
  """
  path = LOG_FILE
  if not path.exists():
    return []

  entries: List[Dict[str, Any]] = []
  with path.open("r", encoding="utf-8") as f:
    for line in f:
      line = line.strip()
      if not line:
        continue
      try:
        obj: Dict[str, Any] = json.loads(line)
      except Exception:
        continue
      if event_type and obj.get("type") != event_type:
        continue
      if campaign_id and obj.get("campaign_id") != campaign_id:
        continue
      entries.append(obj)
  entries.sort(key=lambda e: e.get("ts", ""))
  if limit and limit > 0:
    entries = entries[-limit:]
  entries.reverse()
  return entries


def write_dev_todos(entries: List[dict[str, Any]]) -> None:
  import json as _json
  DEV_TODO_FILE.parent.mkdir(parents=True, exist_ok=True)
  with DEV_TODO_FILE.open("w", encoding="utf-8") as f:
    for e in entries:
      f.write(_json.dumps(e, ensure_ascii=False) + "\n")


def npc_template_path(template_id: str) -> Path:
  safe = "".join(c for c in template_id if c.isalnum() or c in "-_")
  return NPC_TEMPLATES_DIR / f"{safe}.json"


def load_npc_template(template_id: str) -> dict[str, Any]:
  path = npc_template_path(template_id)
  if not path.exists():
    raise FileNotFoundError(f"NPC template {template_id!r} not found at {path}")
  with path.open("r", encoding="utf-8") as f:
    return json.load(f)
