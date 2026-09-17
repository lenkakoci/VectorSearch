# VectorSearch – webové demo vyhledávání

React + Vite + TypeScript + Tailwind. Jedna stránka nad API v `data/scripts/search_api.py`.

```powershell
npm install
npm run dev          # http://localhost:5173, /api se proxuje na http://localhost:8010
npm run build        # dist/
```

API musí běžet: `cd ..\data\scripts; uv run uvicorn search_api:app --reload --port 8010`.
Jinou adresu API nastavíte proměnnou `VITE_API_URL` (dev proxy) nebo `VITE_API_BASE` (build).

Stránka má tři záložky: **Vyhledávání** (pasáže) a **Zeptat se dokumentů**
(odpověď s citacemi) sdílejí filtry; **Architektura** je samostatná statická
stránka bez filtrů a bez volání API.

## Vyhledávání

- Pole „Co hledáte?“ s ukázkovými dotazy a inline prefixy (`autor:Poul …`).
- Přepínač Fulltext / Sémantické / Hybridní / Porovnat. „Porovnat“ spustí jeden
  dotaz ve všech třech režimech vedle sebe; stejný úryvek dostane stejné písmeno.
- Panel „Upřesnit hledání“: autor, organizace, obec, klient, typ, dokument
  (multiselect s počty), období (roky), část zprávy (tělo / přílohy). Každý filtr
  lze vypnout, aniž by se ztratil výběr.
- Karta výsledku: název, odznaky (slova / význam / obojí, příloha), cesta sekce,
  strana, skóre, úryvek se zvýrazněnými slovy (`ts_headline`, tedy i skloněné
  tvary), celý text, kontext ±1 chunk, metadata dokumentu, rozpis skóre.
- Sbalený panel „Expert / debug“: požadavek, lexémy `tsquery`, SQL filtrů, časy,
  počty kandidátů, tabulka pořadí a skóre.

## Zeptat se dokumentů

- Pole „Na co se chcete zeptat?“ s ukázkovými otázkami; poslední z nich v korpusu
  odpověď nemá a ukáže bránu relevance.
- Odpověď se stavem (Odpovězeno / Částečně / Nedostatek podkladů / Bez podkladů),
  větami v pořadí čtení a souhrnem „ověřeno X z Y vět“.
- Citace jako tlačítka: klik sjede na zdroj a zvýrazní v něm ověřený citát.
  Neověřená věta je podtržená vlnovkou a nese důvod od kontroly.
- Zdroje: citované rozbalené, ostatní sbalené; známka od rerankeru, role
  (`nalezeno`, `kontext`, `pod prahem`), sekce, strana, chunk, kontext ±1
  a odkaz „PDF, s. X", který otevře zdrojový posudek na dané straně.
- „Ve zdrojích chybí“ a „Rozpory mezi zdroji“, když je model vyplní.
- Sbalený panel „Expert: průběh odpovědi“: kroky s počty a časy, přesný prompt
  a surová odpověď modelu před kontrolou.
- Průběh odpovědi: dokud se odpovídá, vypisují se kroky tak, jak je server
  hlásí přes server-sent events (`POST /api/answer/stream`). Bez streamování
  se stránka vrátí k obyčejnému `POST /api/answer`.
- Nastavení: počet zdrojů, minimální známka, sousední úryvky a „nová odpověď".
  Změna filtrů odpověď nepřegeneruje, protože každá odpověď stojí volání modelu.
- Odznak „z cache" u odpovědi, kterou server vzal z uložených; expert panel
  u ní říká, že se model nevolal.

## Architektura

Celá pipeline na jedné obrazovce, pro prezentaci a vysvětlení kolegům.

- **Schéma** rozdělené do čtyř fází (zpracování posudku, uložení a index, od
  dotazu k pasážím, od pasáží k odpovědi), 24 boxíků, barva boxíku nese cenu
  kroku (zdarma lokálně / SQL / placené volání Gemini). Dvě retrievalové větve
  (slova, význam) jsou nakreslené jako vidlice, sloučená do RRF.
- Klik na boxík otevře v bočním panelu technologii, co se v kroku děje,
  záludnosti, bezpečnostní opatření (🛡), naměřená čísla a soubory v repu.
- **Témata napříč** pod schématem: měření kvality (tabulky recall@k a MRR),
  bezpečnostní opatření na jednom místě, provoz a nasazení, doladění
  extrakčního schématu z `extra_fields`, otevřené věci a další práce.
- Šipky nahoru/dolů listují kroky v pořadí pipeline, Esc zavře panel;
  „Rozbalit vše" vypíše celý obsah pod sebe pro tisk.
- Nevolá API — data jsou zapsaná v `src/lib/architecture.ts` s datem měření,
  takže záložka funguje i bez běžící databáze.

## Struktura

| cesta | obsah |
| --- | --- |
| `src/App.tsx` | stav stránky, kompozice |
| `src/components/` | SearchBar, ModeSwitch, FilterPanel, MultiSelect, ActiveFilters, ResultList, ResultCard, ScoreBreakdown, ContextView, DocumentInfo, CompareView, DebugPanel |
| `src/components/` (odpovědi) | AskView, AnswerCard, AnswerProgress, SourceList, PipelineTrace |
| `src/components/` (architektura) | ArchitectureView, PipelineMap, StepDetail |
| `src/hooks/` | useSearch, useAnswer |
| `src/lib/modes.ts` | popisy režimů laicky, ukázkové dotazy |
| `src/lib/answers.ts` | stavy odpovědi, popisy kontrol a rolí, ukázkové otázky |
| `src/lib/architecture.ts` | data záložky Architektura: kroky, fáze, témata napříč |
| `src/lib/filters.ts` | stav filtrů a jeho převod na tělo požadavku |
| `src/lib/highlight.tsx` | vykreslení `<mark>` z `ts_headline` bez `innerHTML`, a dohledání citátu ve zdroji |
| `src/test/` | render testy nad odpověďmi zachycenými z API |
| `src/services/api.ts` | volání API |
| `src/types.ts` | zrcadlo Pydantic modelů |
