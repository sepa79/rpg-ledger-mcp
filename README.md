# RPG Ledger MCP Server

Serwer legera do sesji RPG sterowanych przez AI. Udostępnia stan kampanii (postacie, ekwipunek, questy, logi) przez MCP i proste API HTTP, tak żeby np. ChatGPT mógł być Mistrzem Gry / NPC.

## Architektura

- `app.py` – FastAPI + FastMCP
  - MCP tools (używane przez klienta AI):
    - `list_campaigns()` – lista kampanii
    - `get_campaign(campaign_id)` – pełne dane kampanii
    - `get_character(campaign_id, char_id)` – jedna postać
    - `mutate(...)` – modyfikacje legera (gold/hp/xp/notki/deń/questy/ekwipunek itd.)
    - `dev_todo(...)` – narzędzie dla MG/AI do zapisywania TODO w logu
- `data/` – pliki kampanii JSON (np. `kampania-1.json`)
- `logs/` – zdarzenia z gry (`logs.jsonl`)
- `static/index.html` – prosta przeglądarka kampanii w przeglądarce

Serwer HTTP nasłuchuje na porcie `8000`, MCP jest wystawione jako SSE pod `/mcp` (FastMCP over HTTPS/HTTP).

## Uruchomienie przez Docker Compose (zalecane)

Wymagane:
- Docker + Docker Compose

```bash
docker compose up --build
```

To uruchomi dwa kontenery:

- `rpg-ledger-mcp` – serwer FastAPI + MCP na `http://localhost:8000`
- `rpg-ledger-ngrok` – tunel HTTP do `rpg-ledger-mcp:8000` (publiczny URL z ngrok)

W pliku `docker-compose.yml` można wstawić własny `NGROK_AUTHTOKEN`.

Przydatne adresy lokalnie:

- UI kampanii: `http://localhost:8000/`
- API kampanii: `http://localhost:8000/api/campaigns` itd.
- Logi: `http://localhost:8000/api/logs`

## Konfiguracja MCP (klient np. ChatGPT Desktop / inne)

Serwer MCP jest dostępny jako endpoint HTTP SSE:

- URL: `http://localhost:8000/mcp`

W konfiguracji klienta MCP ustaw:

- typ: „HTTP / SSE” (FastMCP)
- endpoint: `http://localhost:8000/mcp` (lub publiczny URL z ngrok)

Po podłączeniu klient powinien widzieć narzędzia MCP (`list_campaigns`, `get_campaign`, `get_character`, `mutate`, `dev_todo`).

## Lokalny development (bez Dockera)

Wymagany Python 3.11+.

```bash
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Potem korzystasz z tych samych URL co wyżej (`http://localhost:8000/...`).

## Dev TODO z poziomu MG / AI

Narzędzie `dev_todo(...)` pozwala MG/AI zapisywać pomysły na rozwój systemu:

- wywołanie MCP `dev_todo(summary=..., details=..., tags=[...])`
- wpis trafia do `logs/logs.jsonl` z `type: "todo"`

Dzięki temu możesz:

- grać sesję,
- pozwalać MG/AI zgłaszać brakujące funkcje jako TODO,
- później przejrzeć `/api/logs` i zaimplementować kolejne kawałki logiki legera.

