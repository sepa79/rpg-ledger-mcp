# RPG Ledger MCP – AGENT NOTES

Te wskazówki są dla agentów modyfikujących ten projekt.

## Stos technologiczny

- Backend:
  - Python 3.11+, FastAPI
  - FastMCP (`mcp.server.fastmcp.FastMCP`) – MCP over HTTP/SSE
- Frontend:
  - Czysty HTML + inline CSS/JS (`static/index.html`)
- Inne:
  - Uvicorn (serwer HTTP)
  - Docker + docker-compose

## Ogólne zasady

- Traktuj log kampanii (`logs/logs.jsonl`) jako **źródło prawdy**:
  - Domyślnie **append-only**.
  - Modyfikuj istniejące wpisy tylko wtedy, gdy:
    - dotyczy to stanu `todo` (done/comment),
    - użytkownik wyraźnie prosi o migrację / naprawę.
- Kampanie:
  - Główne dane są w `data/*.json` – jeden plik na kampanię.
  - Struktura powinna pozostać możliwie czytelna dla człowieka.

## MCP i narzędzia

- `app.py`:
  - `mcp = FastMCP("RpgLedger")` – serwer „gry”:
    - `list_campaigns`, `get_campaign`, `get_character`, `mutate`.
  - `dev_mcp = FastMCP("RpgLedgerDev")` – serwer „dev”:
    - `dev_todo`, `dev_get_logs`, `dev_get_todos`,
    - `dev_request_restart`, `dev_get_ci_status`, `dev_wait_for_deploy`.
- Przy dodawaniu nowych narzędzi:
  - Nadawaj **krótkie, rzeczowe nazwy** (`snake_case`).
  - Zadbaj o docstring opisujący:
    - cel narzędzia,
    - parametry,
    - ewentualne skutki uboczne (np. zmiana kampanii, zapis do loga).

## Mutacje i schema

- Funkcja `mutate(...)`:
  - Podpis ma pozostać zgodny z:
    - `value: Optional[Any] = None`
  - `parsed_value` jest miejscem na normalizację (string → JSON → inne).
- Nowe operacje (`op`):
  - Dodawaj w jednym miejscu w `mutate`, z czytelną sekcją komentarza.
  - Staraj się, by side‑effect zawsze kończył się:
    - `_save_campaign(...)`
    - `_log_event(...)` typu `"mutate"` lub `"history"`.

## Frontend (static/index.html)

- Struktura:
  - Topbar z wyborem kampanii.
  - Lewa kolumna:
    - karta kampanii (summary),
    - panel „Mapa świata” (lista lokacji + status),
    - grid kart drużyny (party view),
    - szczegóły wybranej postaci.
  - Prawa kolumna:
    - karta „Panel” z zakładkami:
      - `Log MCP`
      - `TODOs`
- Best practices:
  - Nie dodawaj nowych frameworków JS – trzymaj się prostego DOM/Fetch.
  - Unikaj nadmiernego zagnieżdżania template stringów (czytelność > spryt).
  - Dla logów:
    - `Log MCP` pokazuje tylko `type: "mutate"` i `type: "history"`.
    - `TODOs` opiera się wyłącznie na `type: "todo"` z polami `done` i `comment`.

## TODO / dev loop

- `dev_todo`:
  - Służy do zapisywania „zadań dla deva” z poziomu MG/AI.
  - Domyślnie wpisy `todo` mają: `done=False`, `comment=""`.
- `/api/todo-status`:
  - Może aktualizować tylko istniejące wpisy `type: "todo"`.
  - Nie powinno tworzyć nowych typów wpisów.

## Docker / deploy

- `docker-compose.yml`:
  - `rpg-ledger-mcp` – serwer FastAPI + MCP (`/mcp`, `/mcp-dev`, `/static`, `/api/...`).
  - `ngrok` – tunel HTTP (nie modyfikuj bez potrzeby; token może być prywatny).
- `Dockerfile`:
  - Minimalne zmiany, tylko jeśli wymagają tego zależności (requirements.txt).

## Styl i porządek

- Zachowuj istniejący styl:
  - brak lintera – trzymamy się aktualnego formatowania.
  - komentarze po polsku są OK, ale zwięzłe.
- Przy większych zmianach:
  - opisuj je w commit message tak, by MG/developer wiedział, co się zmieniło.

