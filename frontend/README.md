# VectorSearch – webové demo vyhledávání

React + Vite + TypeScript + Tailwind. Jedna stránka nad API v `data/scripts/search_api.py`.

```powershell
npm install
npm run dev          # http://localhost:5173, /api se proxuje na http://localhost:8010
npm run build        # dist/
```

API musí běžet: `cd ..\data\scripts; uv run uvicorn search_api:app --reload --port 8010`.
Jinou adresu API nastavíte proměnnou `VITE_API_URL` (dev proxy) nebo `VITE_API_BASE` (build).

Stránka má dvě záložky nad společnými filtry: **Vyhledávání** (pasáže)
a **Zeptat se dokumentů** (odpověď s citacemi).

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
  (`nalezeno`, `kontext`, `pod prahem`), sekce, strana, chunk, kontext ±1.
- „Ve zdrojích chybí“ a „Rozpory mezi zdroji“, když je model vyplní.
- Sbalený panel „Expert: průběh odpovědi“: kroky s počty a časy, přesný prompt
  a surová odpověď modelu před kontrolou.
- Nastavení: počet zdrojů, minimální známka, sousední úryvky a „nová odpověď".
  Změna filtrů odpověď nepřegeneruje, protože každá odpověď stojí volání modelu.
- Odznak „z cache" u odpovědi, kterou server vzal z uložených; expert panel
  u ní říká, že se model nevolal.

## Struktura

| cesta | obsah |
| --- | --- |
| `src/App.tsx` | stav stránky, kompozice |
| `src/components/` | SearchBar, ModeSwitch, FilterPanel, MultiSelect, ActiveFilters, ResultList, ResultCard, ScoreBreakdown, ContextView, DocumentInfo, CompareView, DebugPanel |
| `src/components/` (odpovědi) | AskView, AnswerCard, SourceList, PipelineTrace |
| `src/hooks/` | useSearch, useAnswer |
| `src/lib/modes.ts` | popisy režimů laicky, ukázkové dotazy |
| `src/lib/answers.ts` | stavy odpovědi, popisy kontrol a rolí, ukázkové otázky |
| `src/lib/filters.ts` | stav filtrů a jeho převod na tělo požadavku |
| `src/lib/highlight.tsx` | vykreslení `<mark>` z `ts_headline` bez `innerHTML`, a dohledání citátu ve zdroji |
| `src/test/` | render testy nad odpověďmi zachycenými z API |
| `src/services/api.ts` | volání API |
| `src/types.ts` | zrcadlo Pydantic modelů |
