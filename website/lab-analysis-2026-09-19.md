---
layout: default
---

# Odysseus-Lab — przegląd 2026-09-19: poprawki, ulepszenia, dalszy rozwój

Data: 2026-09-19 · Stan: `main` @ `448b216` (Lab 0.3.1 + UI pass) · Upstream: `dev` @ `3b6c1691` (2026-09-14), `main` @ `934d23c0` (2026-09-05)

Dokument uzupełnia [analizę z 2026-09-13](lab-analysis-2026-09-13.md). Tamten dokument opisuje architekturę, warstwę Lab i kierunki Tier A–C; ten skupia się na tym, co zmieniło się od tamtej pory, co zostało dziś zweryfikowane w kodzie, i na konkretnej, uporządkowanej liście poprawek i ulepszeń.

> **Status wykonania (2026-09-19, po południu):** issues #18–#32 założone (tracking: [#18](https://github.com/RaCzKoViC/Odysseus-Lab/issues/18)); alerty Dependabota włączone; `tmp_pytest_probe/` usunięty; PR-y dla F3, F5, F6, F9 otwarte (patrz #18).

## 1. Co się zmieniło od 2026-09-13

| Obszar | Stan 13.09 | Stan 19.09 |
|---|---|---|
| `main` | `a5fe38d` (0.2.2), PR #10 otwarty | `448b216` = 0.3.1 + PR #17 (wordmark, Liquid Glass, code chrome, strzałki, podgląd załączników). **Od 13.09 wieczorem zero commitów.** |
| Gałęzie lokalne | — | `feat/ios-pwa` = `main` + niezacommitowany `static/icons/apple-touch-icon.png` (180×180). `index.html` nadal linkuje `icon-192.png` jako `apple-touch-icon`. Praca zaczęta, nie dokończona. |
| Otwarte PR | #10 | tylko #15 (Dependabot: `pydantic-core` 2.46.5 → 2.49.0) — **CI czerwone** (pytest 3.11/3.14, Windows, Docker). Przyczyna: `pydantic 2.13.5` wymaga `pydantic-core==2.46.5`, a bump zmienia tylko constraint → `ResolutionImpossible`. |
| Issues w Lab | 0 | 0 — plan rozwoju istnieje tylko w `website/*.md`, nic nie jest śledzone. |
| Dependabot alerts | — | **wyłączone** w ustawieniach repo (API zwraca 403 „disabled"). Pip-audit w CI to jedyna siatka. |
| Upstream `dev` | baza importu `9d5c031` | **+4 commity** (jeden PR #6280: atomowa podmiana cache tokenów w `app.py`, 5 linii + test). Upstream `main` jest starszy niż `dev` (2026-09-05). Tempo commitów spadło, ale w tydzień przybyło ~40 issues „ready for review" z konkretnymi błędami. |
| Kierunki A1–A4 | zaproponowane | **żaden nie rozpoczęty**: `PYTHONUTF8` nie ma ani w CI, ani w `launch-windows.ps1`/`update_windows.bat`; job Windows nadal uruchamia 4 pliki; brak workflow dryfu; ledger Context Engine nadal tylko szacuje schematy; `default_workspace_path` projektu ma jedynego konsumenta w `core/database.py`. |

## 2. Weryfikacja wykonana 2026-09-19

Wszystko poniżej sprawdzone bezpośrednio w kodzie na `main`; nic nie wymaga uruchomionej aplikacji.

### 2.1 Błędy z upstreamu obecne w forku (potwierdzone)

Fork = upstream `dev@9d5c031` + 4 commity, więc świeże zgłoszenia upstreamu dotyczą dokładnie tego kodu. Potwierdzone przez lekturę źródła:

| Upstream | Co | Gdzie w Lab | Dowód |
|---|---|---|---|
| #6326 | SSRF przez narzędzie agenta `manage_endpoints` | `src/agent_tools/admin_tools.py:42-53` | `base_url` z argumentów modelu trafia prosto do `ModelEndpoint(...)` bez żadnej walidacji schematu/hosta; omija logikę trasy HTTP. |
| #6315 | brak walidacji schematu/hosta w `POST /api/model-endpoints` | `routes/model_routes.py:1990-2030` | `_normalize_base` → `resolve_url` → `_rewrite_loopback_for_docker`; nigdzie odrzucenia `file:`, `gopher:` ani polityki adresów prywatnych. Uwaga: LAN/loopback są tu legalne (Ollama), więc poprawka = whitelist `http/https` + polityka, nie ślepa blokada. |
| #6288 | `fire_event()` tworzy task bez trzymania referencji | `src/event_bus.py:33-41` | `loop.create_task(_handle_event(...))` bez zbioru zadań i `add_done_callback`; task może zostać zebrany przez GC przed wykonaniem. |
| #6337 | wywołania narzędzi w płotkach kończą się na pierwszym ``` gdziekolwiek | `src/agent_loop.py:5401` | `re.compile(r'```(\w*)\n([\s\S]*?)```')` — heredoc z zagnieżdżonym ``` rozcina zapis pliku. |
| #6341 | `GET /api/cookbook/hf-gguf-files` zwraca 500 przy każdym błędzie HF | `routes/cookbook_routes.py:3885` | `logger.exception("... %s", repo)` — zmienna nazywa się `repo_id`; w gałęzi `except` leci `NameError`. |

Kandydaci do sprawdzenia w następnej kolejności (nie weryfikowane dziś, ale prawdopodobne, bo kod jest ten sam): #6285 reguły wyłączonych narzędzi zostają w prompcie, **#6290 wydarzenia całodniowe zapisują się dzień wcześniej dla stref na wschód od UTC (dotyczy Polski)**, #6340 CalDAV gubi `EXDATE`, #6342 `manage_memory` edytuje złą pamięć przy pustej 2. linii, #6314 agent kończy przedwcześnie zadania wieloetapowe, #6366/#6299/#6329 stabilność MCP (utrata narzędzi, martwe sesje stdio, bramka zatwierdzeń co drugie wywołanie), #6350 narzędzia Cookbook tylko-do-odczytu omijają politykę nie-admina.

### 2.2 Narzędzia i CI warstwy Lab

- **`scripts/upstream-status` podaje mylący dryf.** Liczy `git rev-list --left-right HEAD...upstream/dev`, a import był squash-commitem `2cfa9c1` bez wspólnego przodka → raport „Lab behind 2090" przy realnych **4** commitach. Poprawka: liczyć od `UPSTREAM_BASE.commit` (`rev-list --count <base>..<ref>`), a `HEAD...` zostawić jako informację pomocniczą.
- **Dependabot i `constraints/`.** Pliki constraints pinują transzytywne zależności (`pydantic-core`), więc każdy pojedynczy bump Dependabota tej klasy będzie czerwony. Potrzebna grupa `pydantic*` w `.github/dependabot.yml` albo ignorowanie `pydantic-core` i odświeżanie constraints skryptem.
- **Service worker.** Wszystkie 105 wpisów `PRECACHE`/`PANEL_PRECACHE` i 42 odwołania statyczne z `index.html` istnieją na dysku (OK). Ale trzy moduły ładowane przez `index.html` **nie są w precache**: `a11y.js`, `assistant.js`, `tourAutoplay.js` — wbrew komentarzowi w `sw.js` („PRECACHE mirrors the `<script type="module">` tags"). Offline te moduły nie wstaną. To dokładnie luka „static asset/route manifest regression" ze `specs/frontend.md`.
- **Windows-clean.** W runtime zostały 3 wystąpienia `read_text()` bez kodowania, wszystkie w generowanym kodzie runnera w `routes/cookbook_routes.py:2524-2558` (wykonywanym na maszynie użytkownika, więc też do poprawy). W testach nadal **31 plików**. Tylko 4 pliki testów mają jakiekolwiek markery platformy Windows.
- **Repo:** pusty katalog `tmp_pytest_probe/` w korzeniu (śmieć po sondzie testowej); `package.json` bez sekcji `scripts` (brak jakiegokolwiek `npm test`/lint dla 118k linii JS).

## 3. Poprawki (P0 — małe, konkretne, do zrobienia w pierwszej kolejności)

Kolejność = stosunek ryzyka do kosztu. Każda pozycja to osobny, mały PR z testem czerwony→zielony; zgodnie z polityką forka żadna nie dotyka hotspotów poza kilkoma liniami.

| # | Poprawka | Pliki | Test | Rozmiar |
|---|---|---|---|---|
| F1 ([#23](https://github.com/RaCzKoViC/Odysseus-Lab/issues/23)) | **SSRF: walidacja `base_url` w `manage_endpoints` i `POST /api/model-endpoints`** — wspólny helper `validate_endpoint_base_url()` (tylko `http/https`, host niepusty, opcjonalna polityka adresów prywatnych z env, domyślnie LAN dozwolony bo lokalne modele) użyty w obu miejscach. | `src/agent_tools/admin_tools.py`, `routes/model_routes.py`, nowy `src/endpoint_url_policy.py` | trasa + narzędzie: `file:///etc/passwd`, `gopher://`, pusty host → 400/błąd narzędzia | S |
| F2 ([#24](https://github.com/RaCzKoViC/Odysseus-Lab/issues/24)) | **`fire_event` trzyma referencje do tasków** — moduł-level `set()`, `add_done_callback(discard)`. | `src/event_bus.py` | test z `gc.collect()` po `fire_event` w pętli | S |
| F3 ([#19](https://github.com/RaCzKoViC/Odysseus-Lab/issues/19)) | **`hf_gguf_files`: `repo` → `repo_id`** + test, że błąd HF daje `{"ok": false}` a nie 500. | `routes/cookbook_routes.py:3885` | route-level z podmienionym `httpx` | XS |
| F4 ([#25](https://github.com/RaCzKoViC/Odysseus-Lab/issues/25)) | **Parser płotków narzędzi odporny na zagnieżdżone ```** — dopasowanie zamknięcia tylko na początku linii (`^```\s*$`, flaga `M`) i preferowanie najdłuższego poprawnego bloku; test z heredoc zawierającym ``` w środku. | `src/agent_loop.py:5401` | jednostkowy na `_code_block_re`/funkcji parsującej | S (ostrożnie: hotspot) |
| F5 ([#20](https://github.com/RaCzKoViC/Odysseus-Lab/issues/20)) | **Dependabot:** zamknąć #15; dodać grupę `pydantic` (`pydantic`, `pydantic-core`, `pydantic-settings`) lub `ignore: pydantic-core`; dodać do `scripts/` odświeżanie constraints (`pip-compile`-podobne) uruchamiane ręcznie. | `.github/dependabot.yml`, `constraints/*` | CI zielone na kolejnym bumpie | XS |
| F6 ([#21](https://github.com/RaCzKoViC/Odysseus-Lab/issues/21)) | **`upstream-status`: prawdziwy dryf od `UPSTREAM_BASE`** (`base..upstream/dev` = 4) + lista dotkniętych hotspotów (`git diff --stat base..ref -- app.py static/app.js src/llm_core.py core/database.py`). | `scripts/upstream-status`, `tests/test_upstream_status.py` | fixture repo z squash-importem | S |
| F7 ([#26](https://github.com/RaCzKoViC/Odysseus-Lab/issues/26)) | **SW precache = tagi modułów w `index.html`** — dodać 3 brakujące moduły, podbić `CACHE_NAME`, dodać test regresji: każdy `<script type="module" src>` z `index.html` jest w `PRECACHE`, każdy wpis precache istnieje na dysku. | `static/sw.js`, `tests/test_sw_precache_manifest.py` | nowy test (zamyka lukę ze `specs/frontend.md`) | S |
| F8 ([#27](https://github.com/RaCzKoViC/Odysseus-Lab/issues/27)) | **Dokończyć `feat/ios-pwa`:** `<link rel="apple-touch-icon" sizes="180x180" href="/static/icons/apple-touch-icon.png">`, `apple-mobile-web-app-title`, poprawić per-route podmianę ikony (`index.html:168`) i `manifest.json` (`id`, `display_override`), dopisać ikonę do precache. | `static/index.html`, `static/manifest.json`, `static/sw.js` | test asset-manifest z F7 | S |
| F9 ([#22](https://github.com/RaCzKoViC/Odysseus-Lab/issues/22)) | **Synchronizacja upstreamu `dev` (+4)** osobnym PR wg `website/upstream.md`: cherry-pick #6280 (5 linii w `app.py` + `tests/test_token_cache_atomic_swap.py`), potem `UPSTREAM_BASE` → `3b6c1691`. | `app.py`, `UPSTREAM_BASE`, `FORK.md` | istniejący test z upstreamu | XS |
| F10 ([#18](https://github.com/RaCzKoViC/Odysseus-Lab/issues/18)) | **Porządki:** usunąć `tmp_pytest_probe/`; włączyć Dependabot alerts w ustawieniach repo (jedno kliknięcie, zero kodu); założyć issues w Lab dla F1–F9 i A1–A4, żeby plan nie żył tylko w `website/`. | repo settings, GitHub | — | XS |

Szacunek: F1–F10 to ~1 tydzień pracy z testami; efekt to 5 zamkniętych realnych błędów (w tym 2 bezpieczeństwa), zielony Dependabot, wiarygodny wskaźnik dryfu i działające PWA na iOS.

## 4. Ulepszenia (P1 — Tier A z 13.09, doprecyzowane)

### U1. Windows-clean (A3, [#28](https://github.com/RaCzKoViC/Odysseus-Lab/issues/28)) → 0.3.2

1. `PYTHONUTF8=1` w: jobie `windows-foundation`, `launch-windows.ps1`, `update_windows.bat`, `build-windows-portable.ps1` i w generowanym runnerze Cookbooka.
2. Mechaniczna poprawka 31 plików testów: `read_text()` → `read_text(encoding="utf-8")` (jeden commit, kandydat do PR upstream — zmniejsza diff forka).
3. Job Windows uruchamia **pełny pytest** z **ledgerem znanych niepowodzeń** (`tests/known_failures_windows.txt`, czytany przez `conftest.py` jako `xfail(strict=True)`), zamiast 4 plików. Punkt startowy ledgera = tabela §8 z analizy 13.09 (115 fail / 23 error). Strict-xfail sprawia, że każda naprawa musi zostać zdjęta z listy — ledger tylko maleje. Zamyka lukę „no canonical known-failing ledger" ze `specs/testing-devops.md`.
4. Największe klastry do naprawy po kolei: testy JS budujące `import()` z absolutnej ścieżki Windows (→ `pathlib.Path(...).as_uri()`; ~40 testów jednym helperem), `tests/run_focus.py` zakładający `./venv/bin/python`, code-nav/confinement zakładające `/tmp` i `~/.ssh`.

### U2. Automatyczny raport dryfu upstreamu (A4, [#29](https://github.com/RaCzKoViC/Odysseus-Lab/issues/29))

Workflow `upstream-drift.yml` (cron tygodniowy + `workflow_dispatch`): `git fetch upstream`, `scripts/upstream-status --json` (po F6), `git diff --stat base..upstream/dev -- <hotspoty>`, lista nowych issues upstreamu z etykietą `bug` przez `gh api` → jeden issue „Upstream drift YYYY-WW" w Lab (aktualizowany, nie mnożony). Dzięki temu §2.1 tego dokumentu robi się sam.

### U3. Projekt jako granica wykonania agenta (A2, [#30](https://github.com/RaCzKoViC/Odysseus-Lab/issues/30)) → 0.4.0

Bez zmian względem 13.09, z jednym doprecyzowaniem po dzisiejszym sprawdzeniu: `default_workspace_path` nie ma dziś **żadnego** konsumenta poza ORM, więc pierwszy krok jest czysto addytywny: w `routes/workspace_routes.py`/`src/tool_execution.py` „jeśli sesja ma `project_id` i użytkownik nie wybrał folderu ręcznie → cwd = workspace projektu". Potem domyślny model/endpoint projektu w czacie, na końcu izolacja RAG (kolekcje Chroma z sufiksem projektu — uwaga na kontrakt nazw kolekcji w `FORK.md`: nowe kolekcje tak, zmiana istniejących nie).

### U4. Context Engine od obserwacji do sterowania (A1, [#31](https://github.com/RaCzKoViC/Odysseus-Lab/issues/31)) → 0.4.x

Po U3, bo profil „slim agent" ma sens dopiero, gdy wiadomo, w jakim projekcie/repo agent pracuje. Najpierw prawdziwy pomiar schematów narzędzi (dziś `budget.py` szacuje), potem stabilne identyfikatory bloków i polityka pin/wyklucz. Upstream #6285 (reguły wyłączonych narzędzi zostają w prompcie) to naturalny pierwszy test tej warstwy.

### U5. Frontend: minimalny pipeline jakości ([#32](https://github.com/RaCzKoViC/Odysseus-Lab/issues/32))

`package.json` nie ma nawet `scripts`. Bez budowania: `npm run check` = `node --check` dla 85 modułów (jest już w CI) + walidacja grafu importów (skrypt: każdy `import` względny w `static/js` wskazuje istniejący plik) + test z F7. Koszt XS, łapie klasę błędów „CSS/JS się nie załadował", którą upstream wymienia jako główną w `ROADMAP.md`.

## 5. Dalszy rozwój (P2 — Tier B/C, bez zmian, z aktualizacją kolejności)

- **B3 Eval harness agenta przed B1 sandboxem**: bez deterministycznego zestawu zadań (fake-LLM + mały model Ollama) ani U4, ani poprawki #6314 („agent kończy przedwcześnie") nie da się uczciwie zmierzyć. `specs/agent-tools.md` wprost wskazuje brak e2e testu `stream_agent_loop`.
- **B1 Sandbox per projekt** domyka F1 i „known gaps" 1 i 4 z `THREAT_MODEL.md`; na Windows zaczynać od restricted cwd + deny-lista (`data/` z sekretami — luka ze `specs/persistence.md`).
- **B2 Artefakty i zapis w Files** (bundle v2) — po U3.
- **C1 adapter RacDev Core, C2 PR-y do upstreamu (encoding, F2, F3 nadają się od razu), C3 OTLP** — bez zmian.
- **Świadomie nie teraz**: i18n, przebudowa frontendu, nowe motywy, Postgres domyślnie.

## 6. Proponowana sekwencja

| Okno | Zakres | Wersja |
|---|---|---|
| Tydzień 1 | F3, F5, F6, F9, F10 (najtańsze), potem F1, F2, F7, F8 | 0.3.2 |
| Tydzień 2 | F4 + U1 (PYTHONUTF8, 31 plików, ledger strict-xfail, pełny job Windows), U2 workflow dryfu, U5 | 0.3.3 |
| Tydzień 3–5 | U3 projekt jako workspace agenta (cwd → model → RAG) | 0.4.0 |
| Tydzień 6–8 | B3 eval harness, U4 slim profile + pomiar schematów | 0.4.x |
| Miesiąc 3+ | B1 sandbox, B2 artefakty, C1–C3 | 0.5.x |

Zasada procesu (sprawdzona w RacOS): 1 PR = 1 problem, test czerwony → zielony, opis PR wg szablonu (`check-pr-description.js` wymaga sekcji Summary / Linked Issue / Type of Change / How to Test / Screenshots), synchronizacja upstreamu zawsze osobnym PR.

## 7. Pułapki (uzupełnienie §8 z 13.09)

- Po dodaniu remote `upstream` **`gh` domyślnie celuje w upstream, nie w Lab** (preferuje remote o nazwie `upstream`): `gh pr list` pokaże PR-y `odysseus-dev/odysseus`. Używać `-R RaCzKoViC/Odysseus-Lab` albo `gh repo set-default RaCzKoViC/Odysseus-Lab`.
- `scripts/upstream-status` do czasu F6 pokazuje „behind ~2090" — ignorować, liczyć `git rev-list --count $(jq -r .commit UPSTREAM_BASE)..upstream/dev`.
- Systemowy Python 3.12 nie ma zależności projektu (brak `fastapi`); do pytest potrzebny venv z `constraints/py311.txt` (~3 min instalacji, ~6 min pełny bieg z `PYTHONUTF8=1`).
- Gałąź `feat/ios-pwa` nie ma commitów; ikona 180×180 jest tylko w drzewie roboczym — nie zgubić przy `git checkout`/`stash`.
