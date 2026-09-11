# VectorSearch – webové demo vyhledávání

React + Vite + TypeScript + Tailwind. Jedna stránka nad API v `data/scripts/search_api.py`.

```powershell
npm install
npm run dev          # http://localhost:5173, /api se proxuje na http://localhost:8010
npm run build        # dist/
```

API musí běžet: `cd ..\data\scripts; uv run uvicorn search_api:app --reload --port 8010`.
Jinou adresu API nastavíte proměnnou `VITE_API_URL` (dev proxy) nebo `VITE_API_BASE` (build).

## Co stránka umí

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

## Struktura

| cesta | obsah |
| --- | --- |
| `src/App.tsx` | stav stránky, kompozice |
| `src/components/` | SearchBar, ModeSwitch, FilterPanel, MultiSelect, ActiveFilters, ResultList, ResultCard, ScoreBreakdown, ContextView, DocumentInfo, CompareView, DebugPanel |
| `src/lib/modes.ts` | popisy režimů laicky, ukázkové dotazy |
| `src/lib/filters.ts` | stav filtrů a jeho převod na tělo požadavku |
| `src/lib/highlight.tsx` | vykreslení `<mark>` z `ts_headline` bez `innerHTML` |
| `src/services/api.ts` | volání API |
| `src/types.ts` | zrcadlo Pydantic modelů |
