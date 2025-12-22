# RPG Ledger MCP Server

Serwer legera do sesji RPG sterowanych przez AI. Udostępnia stan kampanii (postacie, ekwipunek, questy, logi) przez MCP i proste API HTTP, tak żeby np. ChatGPT mógł być Mistrzem Gry / NPC.

## Architektura

- `app.py` – FastAPI + FastMCP
  - MCP tools (używane przez klienta AI):
    - `list_campaigns()` – lista kampanii
    - `get_campaign(campaign_id)` – pełne dane kampanii
    - `get_character(campaign_id, char_id)` – jedna postać
    - `list_locations(campaign_id)` – lista lokacji kampanii
    - `list_factions(campaign_id)` – lista frakcji kampanii
    - `create_campaign(campaign_id, name, from_campaign_id, overwrite)` – tworzenie kampanii
    - `create_character(campaign_id, character)` – dodanie nowej postaci
    - `update_character(campaign_id, char_id, patch)` – modyfikacja istniejącej postaci
    - `upsert_location(campaign_id, location)` – dodawanie/aktualizacja lokacji
    - `delete_location(campaign_id, location_id_or_name)` – usunięcie lokacji po id lub nazwie
    - `faction_rep_add(campaign_id, faction_id, delta, name)` – zmiana reputacji frakcji
    - `upsert_faction(campaign_id, faction)` – dodanie/aktualizacja frakcji (id, name, rep, description)
    - `mutate(...)` – modyfikacje legera (gold/hp/xp/notki/deń/questy/ekwipunek itd.)
    - `spawn_npc_group(campaign_id, template_id, ...)` – generowanie grupy NPC z szablonu
    - `dev_todo(...)` – narzędzie dla MG/AI do zapisywania TODO w logu
    - `save_campaign_snapshot(campaign_id, slot)` / `restore_campaign_snapshot(campaign_id, slot)` – snapshoty kampanii
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
- wpis trafia do osobnego pliku `logs/dev-todos.jsonl` z `type: "todo"`,
  odczytywanego przez endpoint `/api/dev-todos` i zakładkę TODO w UI

Dzięki temu możesz:

- grać sesję,
- pozwalać MG/AI zgłaszać brakujące funkcje jako TODO,
- później przejrzeć `/api/logs` i zaimplementować kolejne kawałki logiki legera.

## Kampania testowa / test pack

Żeby nie zaśmiecać logów głównej kampanii, w katalogu `data/` jest osobna kampania testowa:

- plik: `data/kampania-test.json`
- `id`: `kampania-test`
- zawiera prostą mapę (`karczma` ↔ `las-testowy`) i dwie postacie (`test-warrior`, `test-mage`).

Rekomendacja:

- do ręcznych testów MCP/UI wybieraj w topbarze kampanię „Kampania Testowa”,
- w narzędziach MCP (`mutate`, `roll_dice`, itp.) używaj `campaign_id="kampania-test"`.

Dzięki temu wpisy testowe w `logs/logs.jsonl` będą odseparowane od właściwej kampanii po `campaign_id`.

### E2E test pack (lokalnie)

Jest też prosty E2E test dla kampanii testowej (bezpośrednio po HTTP):

```bash
docker compose up -d
python scripts/e2e_test_pack.py
```

Test:

- sprawdza dostępność serwera na `http://localhost:8000`,
- upewnia się, że `kampania-test` istnieje w `/api/campaigns`,
- przed testem przywraca plik `data/kampania-test.json` z szablonu `data/kampania-test.template.json`,
- wykonuje kilka mutacji na kampanii testowej (`hp_add`, `gold_add`, `location_set`),
- weryfikuje, że zmiany w stanie oraz wpisy w `logs/logs.jsonl` są zgodne z oczekiwaniami,
- po udanym teście ponownie przywraca `data/kampania-test.json` z szablonu (logi pozostają append-only).
