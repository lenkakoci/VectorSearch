# Co pipeline stojí a kde se dá ušetřit

Analýza nákladů převodu i dotazování, 2026-10-07. Odpovídá na otázku, kde by
stačil levnější model, aniž by se to zaplatilo kvalitou výstupu.

Z doporučení je **zapnuté jen první** — čtení `usage_metadata`, které nic
nestojí a nic nemění. Ostatní jsou návrhy; každý nese úsporu, riziko a to, co by
se muselo změřit, než se zapne.

**Značení zdroje u každého čísla:**

| | |
| --- | --- |
| **[měřeno]** | skutečný účet Google (2026-10-02, 2026-10-03) nebo přepočet z `data/processed/` |
| **[dopočteno]** | odvozeno ze seznamových cen, uveden postup |
| **[neověřeno]** | není v repu ani na účtu — nutno dohledat na <https://ai.google.dev/pricing> |

Seznamové ceny: `gemini-3.7-flash` **$0.75 vstup / $3.75 výstup** za 1M tokenů,
`gemini-embedding-001` **$0.15** za 1M. **[měřeno]** — a cena flashe je zapsaná
jako platná **do 2026-12-31**, což znamená, že rozhodnutí o modelu má termín:
po Novém roce se účet může zvednout sám, bez jediné změny v kódu.

Kurz dopočtený z účtu: embeddingy byly 19 % z 34,42 Kč = 6,54 Kč za 2 239 úryvků
po ~1 005 tokenech, tedy 2,25 M tokenů × $0.15/M = $0,338 → **≈ 19,3 Kč za
dolar**. Tím se dá přepočítat cokoli dalšího. **[dopočteno]**

---

## 1. Jedna otázka: 0,82 Kč, a 84 % z toho je hodnocení

Měřeno na sedmi otázkách přes `POST /api/answer` dne 2026-10-03, 5,71 Kč
celkem. **[měřeno]**

| krok | podíl | cena | co přečte |
| --- | ---: | ---: | --- |
| hodnocení kandidátů (2 volání) | **84 %** | 0,69 Kč | **všech 40 kandidátů v plném znění**, ~26 tis. tokenů |
| odpověď (1 volání) | ~13 % | 0,11 Kč | nejvýš 8 úryvků + 4 sousedy, medián 4 332 tokenů |
| embedding dotazu | < 1 % | — | jeden řádek textu |

To je celá podstata: **platíš pětkrát víc za rozhodnutí „je to relevantní" než
za samotnou odpověď.**

Proč tak hodně: `rerank_service.py:153` posílá do promptu `chunk_raw` **bez
jakéhokoli zkrácení**.

```python
"text": hit.get("chunk_raw") or "",
```

Úryvky mají průměr 613 a medián 706 tokenů (měřeno nad `token_count` všech
3 739 úryvků v parquetech), takže 40 kandidátů je ~24,5 tis. tokenů, k tomu
405tokenová instrukce hodnotitele dvakrát, protože se posílá v každé dávce.
Odpovídající model proti tomu vidí nejvýš 8 úryvků se stropem 10 tis. tokenů
(`context_builder.py:46-49`) a reálně medián 4 332. **[měřeno]**

Z 33 dotazů zaznamenaných v `data/processed/answers/asked.jsonl` bylo 19
placených a 10 ze cache, při 16 různých otázkách. Demo tedy dosud stálo
**~16 Kč na odpovědích**. **[dopočteno]**

## 2. Jeden přeběh korpusu: ~50 Kč

Měřeno na účtu za 2026-10-02: 34,42 Kč za 39 plných přeběhů nad 31 dokumenty,
1 868 stran, 2 239 embeddovaných úryvků (ten den žádné hodnocení ani odpovídání).
**[měřeno]**

- jeden plný přeběh průměrného 48stránkového posudku: **0,88 Kč**, z toho
  extrakce 0,71 Kč a embeddingy 0,17 Kč
- **0,018 Kč za stránku PDF**, 0,003 Kč za embeddovaný úryvek
- plný re-ingest dnešního korpusu (cena `SCHEMA_VERSION` bumpu): **~50 Kč**
- rozptyl je obrovský: 0,27 Kč (Lednice, 11 stran) až **7,86 Kč**
  (Monitoring, 571 úryvků). **Účet určuje velikost, ne počet.**

Struktura: extrakce vstup 63 %, extrakce výstup 17 %, embeddingy 19 %.
Seznamové ceny reprodukují účet s odchylkou 6 %.

Kde ten objem leží: `extract_reports.py:239` posílá **celý Markdown v jednom
volání**, bez dělení a bez zkrácení. Korpus je 2 176 014 tokenů (cl100k nad
47 soubory) a **dva dokumenty jsou 32 % toho objemu** —
`GF_P188240_ZZ Sedmirohé 10 sond` 348 982 tokenů a
`GF_P188407_DZ_Monitoring_10_2023` 335 029. Zároveň jsou to ty dva svazky, které
`CLAUDE.md` vede jako nevyřešenou strukturální položku. **[měřeno]**

---

## 3. Skrytá položka: thinking tokeny

**Výstupní tokeny jsou pětkrát dražší než vstupní** ($3.75 vs $0.75). A nikde v
repu není nastaven `thinking_config` ani `max_output_tokens` — nula výskytů
napříč všemi třemi placenými voláními. Na flash modelu 3.x je thinking
defaultně zapnutý a účtuje se jako výstup. **[měřeno]**

### U hodnocení

Rozpočet 0,69 Kč za hodnocení při seznamových cenách nevychází:

| položka | tokeny | cena |
| --- | ---: | ---: |
| vstup (40 úryvků + 2× instrukce + metadata) | ~25,6 tis. cl100k, tj. 30–33 tis. dle Gemini | 0,44–0,48 Kč |
| deklarovaný výstup (40 známek s krátkým důvodem) | ~600 | 0,04 Kč |
| **nevysvětlený zbytek** | | **0,17–0,28 Kč** |

Zbytek odpovídá **2 300–3 900 thinking tokenům na otázku**, tedy 1 200–1 950 na
volání, a **25–40 % ceny nejdražšího kroku**. Poznámka k účtu to podporuje
nezávisle: seznamové ceny reprodukují účet s odchylkou 6 % a thinking je tam
uveden jako pravděpodobný zbytek. Rozpětí vzniká z neznámého poměru mezi
tokenizérem Gemini a `tiktoken` — `README.md:353` ho uvádí jako 10–30 %.
**[dopočteno]**

### U extrakce

Výstup byl 17 % z 34,42 Kč = 5,85 Kč = $0,303, při $3.75/M tedy 80 800
výstupních tokenů na 39 přeběhů, **2 073 tokenů na jednu extrakci**. Samotné
JSON (summary 3–5 vět, findings, recommendations, extra_fields) má odhadem
700–1 200 tokenů. Zbývá **~900–1 400 thinking tokenů na dokument**, tedy
7–11 % celého ingestu. **[dopočteno]**

### Tohle se dá zjistit zdarma — a od 2026-10-07 se to zjišťuje

`response.usage_metadata` nese `thoughts_token_count`, `prompt_token_count`,
`candidates_token_count` i `cached_content_token_count` a **přijde s každým
voláním, které se stejně uskuteční** — ověřeno v `google-genai` 2.19.0, který je
v `pyproject.toml` zamčený. Až do 2026-10-07 to kód nikdy nepřečetl: v celém
repu nebyl jediný výskyt `usage_metadata`. **[měřeno]**

Je to jediná položka téhle analýzy, u které se velikost výhry dá potvrdit nebo
vyvrátit bez zaplacení čehokoli navíc. Proto je jako jediná hotová — viz
doporučení 1 níž.

**Embeddingy takhle měřit nejde.** `EmbedContentResponse` nenese token usage,
jen `billable_character_count`, a ten je podle vlastního popisu v SDK jen pro
Vertex. Embeddingová polovina ingestu tedy zůstává lokálním odhadem z
`chunker.count_tokens` — což je u ní únosné, protože cena embeddingu je známá
($0.15/1M) a nejsou v ní žádné výstupní ani thinking tokeny.

---

## 4. Jaké modely jsou skutečně k dispozici

Zjištěno z `client.models.list()` dne 2026-10-07 — 62 modelů. Relevantní:
**[měřeno]**

| model | vstup | poznámka |
| --- | ---: | --- |
| `gemini-3.7-flash` | 1 048 576 | dnešní volba pro extrakci, hodnocení i odpověď |
| `gemini-3.8-flash` | 1 048 576 | novější flash téže třídy |
| `gemini-3.5-flash-lite` | 1 048 576 | **nejnovější lite úroveň** |
| `gemini-3.1-flash-lite` | 1 048 576 | starší lite |
| `gemini-2.5-flash-lite` | 1 048 576 | nejstarší lite |
| `gemini-flash-lite-latest` | 1 048 576 | alias na nejnovější lite |
| `gemini-embedding-001` | 2 048 | dnešní volba |
| `gemini-embedding-2` | 8 192 | **už není preview, je GA** |

Dvě věci, které z toho seznamu vyplývají:

**`gemini-3.7-flash-lite` ani `gemini-3.8-flash-lite` neexistují.** Levnější
hodnotitel tedy znamená krok o generaci zpět, na `gemini-3.5-flash-lite`. To
není nic, co by se dalo rozhodnout od stolu — je to přesně otázka, na kterou
odpovídá `eval_retrieval.py`.

**Komentář v `.env.template:21` je překonaný.** Říká, že
`gemini-embedding-2-preview` je „still in preview"; `gemini-embedding-2` je
mezitím GA a bere 8 192 vstupních tokenů proti dnešním 2 048. Na cenu to samo
nemá vliv, ale ruší to starost o strop: dnešní `chunk_text` má po přidání
prefixu průměr 1 005 tokenů a maximum 1 362, tedy jen ~686 tokenů rezervy.

Všechny flash i lite modely podporují `batchGenerateContent`, oba embeddingové
`asyncBatchEmbedContent`.

Ceny lite úrovně **v repu nikde nejsou** a odsud je nedohledám. Všechny
dopočty níž jsou proto podmíněné: *„pokud je lite pětina flashe, pak…"*.
**[neověřeno]**

---

## 5. Doporučení, v pořadí podle rizika

### 1) Přečíst účet — HOTOVO 2026-10-07

Zachyceno na všech třech generativních voláních. `gemini_auth.usage_of()` čte
`prompt_token_count`, `candidates_token_count`, `thoughts_token_count`,
`cached_content_token_count` a `total_token_count`; `add_usage()` je sčítá, takže
dvě hodnotící volání jedné otázky jsou jedno číslo.

Kam to teče:

- **hodnocení** → `stats["usage"]` v `rerank_service.GeminiGrader.grade()`, a
  tím existující cestou do `search.debug["rerank"]`
- **odpověď** → `trace["usage"]` v `answer_service.answer()` jako
  `{grading, answer, total}`, plus jeden řádek v logu na otázku
- **extrakce** → klíč `extraction_usage` v `processed/extracted/<stem>.json`,
  vedle `extraction`, plus řádek v logu
- **log dotazů** → pole `usage` v `asked.jsonl`, hned u `cache: hit|miss`

Tři věci, na kterých záleží, aby se dalo sčítat:

1. **Známka z cache se neúčtuje.** `stats["usage"]` nese jen volání, která
   `grade()` skutečně udělal, ne známky z paměti nebo z disku.
2. **Cache hit hlásí nulu.** Uložená odpověď si pamatuje, co stála poprvé;
   kdyby to hlásila znovu, součet přes `asked.jsonl` by první zaplacení počítal
   dvakrát. Je to stejná past, jakou už má `server_ms`, který na hitu hlásí
   původní čas.
3. **Zavřený práh hlásí hodnocení a nulovou odpověď**, protože to je přesně
   to, co se stalo.

Nezměnilo se nic, co se posílá ani co se vrací, takže žádný bump
`SCHEMA_VERSION`, `MARKDOWN_VERSION` ani `CHUNKER_VERSION`. `extraction_usage`
je sourozenec `extraction`, nikoli jeho součást, a `build_context_prefix` čte
jen `extraction` — žádný `chunk_text` a tedy žádný embedding se tím nemění.
Na disku se dosud nezměnil ani jeden soubor: změna je nečinná, dokud
neproběhne placené volání.

**První reálná čísla přijdou sama**, bez zaplacení čehokoli navíc: hodnocení a
odpověď s první novou otázkou v demu (cache hit model nevolá), extrakce s dalším
ingestovaným dokumentem. Teprve pak se rozhoduje o bodech 2 a 3 — do té doby
stojí na dopočtu.

### 2) Zastropovat thinking u hodnotitele

`types.ThinkingConfig(thinking_level=MINIMAL)` nebo `thinking_budget=0` — obojí
SDK podporuje.

**Úspora: 0,17–0,28 Kč z 0,82 Kč na otázku, tedy 20–34 %.** Zároveň útok na
latenci: hodnocení je nejpomalejší krok, 7–13 s u nové otázky, a thinking je
jeho součástí.

Hodnocení je klasifikace do čtyř tříd s pevným schématem `GradeList` — ne úloha,
kde by uvažování nahlas mělo co přidat.

**Riziko:** známky se tím mohou pohnout, a hodnocení je současně relevanční
prahovač, takže pohyb známek se přenáší do toho, zda se vůbec odpoví.

**Měřit:** `eval_retrieval.py --mode rerank` před a po. Sledovat recall@5
(dnes 0,924), recall@40 (0,956), MRR (0,806) a hlavně dvě čísla z prahu:
`relevant_passed` 33/34 a `unanswerable_closed` 6/6.

### 3) Levnější hodnotitel — největší úspora a nejsnazší experiment

`GEMINI_RERANK_MODEL` **už existuje** (`pipeline_common.py:115`), dnes není
nastavený a padá fallbackem na `GEMINI_MODEL`:

```python
rerank_model=os.getenv("GEMINI_RERANK_MODEL") or os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
```

Jedna řádka v `.env`, **žádná změna kódu**, a invaliduje to jen grade cache —
nic z korpusu. `rerank_model` je záměrně vynechaný z `pipeline_config()`.

**Úspora:** pokud je lite pětina flashe, otázka padne z 0,82 Kč na ~0,27 Kč.
S bodem 2 dohromady na **~0,2 Kč, tedy čtyřnásobné zlevnění bez dotknutí
odpovídajícího modelu**. **[neověřeno — závisí na ceně lite]**

**Riziko:** lite je o generaci starší model a hodnocení drží práh, tedy i
schopnost mlčet. Právě práh je to, co dnes dělá odmítnutí možným: známka 2
pustila relevantní úryvek u 33 ze 34 odpovědných otázek a nic u všech 6
neodpovědných.

**Dvě pasti při měření**, obě ověřené v kódu:

- Klíč answer cache obsahuje `answer_model`, ale **ne `rerank_model`**
  (`answer_cache.py:78-85`). Po záměně hodnotitele se budou dál servírovat staré
  odpovědi a A/B nenaměří nic, pokud se cache neobejde (`--no-cache`, resp.
  `fresh=True`).
- Ani `eval_retrieval.py`, ani `eval_answers.py` nemají přepínač na model
  hodnotitele — A/B se dnes dělá přepnutím proměnné prostředí mezi běhy.
  Výsledkový JSON `rerank_model` naštěstí zapisuje, takže běhy jsou zpětně
  rozlišitelné.

### 4) Nezahazovat zaplacené známky při každém ingestu — zdarma, nulové riziko

Oba cache klíče obsahují `corpus_fingerprint()`, což je mtime a velikost
`manifest.json` (`answer_cache.py:52-65`). Přidání jednoho reportu tedy
zneplatní **všech 58 souborů se známkami a 18 uložených odpovědí**, i pro
dokumenty, kterých se ingest vůbec nedotkl. Při 16 různých dotazech v demu je to
**~11 Kč v zaplacených známkách zahozených při každém ingestu** (realizuje se,
až když se otázka zopakuje).

Opravou je fingerprint **na dokument**, ne na korpus: známka patří dvojici
(dotaz, úryvek) a úryvek patří jednomu dokumentu, takže ho může zneplatnit jen
ten dokument.

Docstring `grade_cache.py:12-15` vysvětluje, proč tam fingerprint je — `chunk_id`
je `uuid5(document_id:chunk_index)` a přežije přechunkování i tehdy, když se
text pod ním změní celý, takže bez fingerprintu by se známka včerejšího textu
servírovala na dnešní. **Per-dokumentový fingerprint tuhle obranu neoslabuje,
jen zpřesňuje:** zneplatní se právě to, co se změnilo.

U odpovědí fingerprint nechat korpusový — tam je širší invalidace správná,
protože nový dokument může změnit, co se vůbec dalo najít.

### 5) Zkrátit text kandidátů pro hodnocení — jen změřené, a až po bodech 2 a 3

Vstup je ~85 % ceny hodnocení, takže zkrácení na ~300 tokenů by ušetřilo
~0,25 Kč na otázku. **Je to ale nejrizikovější položka seznamu** a pořadí je
podstatné: pokud lite hodnotitel projde, cena za token spadne tak, že se tohle
riziko nemusí vyplatit brát vůbec.

Rizika konkrétně:

- Známku 3 dostává úryvek, který *obsahuje požadovaný údaj*. Leží-li ten údaj na
  konci úryvku, hlavové zkrácení ho skryje a známka padne — práh se zavře. V
  golden setu je **12 ze 40 otázek typu `exact`**.
- Distribuce je nahoře utažená: medián 706, p90 791, maximum 800 tokenů (strop
  chunkeru). **Nejsou tu žádné extrémy k odříznutí** — krátil by se skutečný
  obsah.
- `ts_headline` se shodujícími se fragmenty **už SQL počítá zdarma**
  (`search_service.py:240-242`) a je to přesně ten obsah, který hodnotitel
  potřebuje. Jenže je `NULL`, když úryvek nemá lexikální shodu — tedy právě u
  kandidátů z vektorové větve. Samotný headline tedy stačit nemůže; muselo by to
  být hlava plus shodující se fragmenty, což je výrazně víc kódu než body 2 a 3.

### 6) Batch API pro celokorpusové přeběhy — nulové riziko kvality

`gemini-3.7-flash` podporuje `batchGenerateContent` a `gemini-embedding-001`
`asyncBatchEmbedContent`; `client.batches.create()` i `create_embeddings()` v SDK
2.19.0 přijímají inlined requesty na Developer API (klíč), takže není potřeba GCS.

**Stejný model, stejný prompt, stejná teplota — tedy nulové riziko kvality** za
přibližně poloviční cenu. `SCHEMA_VERSION` bump z ~50 Kč na ~25 Kč.

Cena je latence: výsledek přijde s odstupem až 24 hodin. Proto **jen pro
celokorpusové přeběhy**. Přidání jednoho reportu musí zůstat synchronní — na
nový dokument se potřebuješ podívat hned, což je celý postup v
`.claude/skills/add-reports/SKILL.md`.

Vedlejší výhra: batch nepodléhá minutové kvótě, takže u dvou velkých svazků
zmizí riziko, že 429 vynutí retry a **přeúčtuje celý 350tisícitokenový vstup
znovu** — dnešní retry posílá celý Markdown pokaždé.

### 7) Prefix `KONTEXT:` — jen jako přívěsek k přechunkování, které stejně přijde

**43,3 % všech embeddovaných tokenů je opakovaný kontextový prefix** — 1 112 241
z 2 570 320. Jeden ~900znakový řetězec duplikovaný 62× v průměrném dokumentu a
186× v `Monitoring`. **[měřeno]**

Jenže embeddingy jsou jen 19 % ingestu, takže vyhození `summary` z prefixu
ušetří **~2,6 Kč na celém korpusu** — a `CONTEXTUALIZE_CHUNKS` jde do
`chunk_params_hash`, takže **měření té úspory stojí přechunkování a
přeembeddování celého korpusu, tedy násobně víc, než se ušetří.**

Skutečná výhra proto není v penězích, ale ve struktuře. `build_context_prefix`
(`chunk_and_embed.py:181-183`) vkládá do prefixu LLM generovaný `summary`, a ten
se podle měření projektu mění i při `temperature=0.0`. Proto **každá re-extrakce
dnes zneplatní 100 % embeddingů dokumentu** — past popsaná v `CLAUDE.md` a
přímo zapsaná v docstringu `cached_embeddings`:

> Keyed on `chunk_text`, the text that actually went to the model - context
> prefix included - so a changed extraction changes the prefix and misses on
> purpose.

Bez `summary` v prefixu by `SCHEMA_VERSION` bump přestal platit embeddingovou
polovinu, tedy ~7 Kč za každý bump a hlavně by zmizela past.

**Doporučení: nedělat samostatně.** Přivěsit k bodu 1 v „Proposed next work"
(usazení extrakčního schématu), které přechunkování platí tak jako tak, a při té
příležitosti změřit `eval_retrieval.py` před a po — kontextový prefix tam je z
důvodu kvality, ne z rozmaru.

---

## 6. Co nedělat, a proč

Každá z těchto věcí vypadá jako úspora a je **měřeně** špatná:

**Snižovat počet kandidátů ze 40.** Měřeno nad golden setem: 24 kandidátů srazí
recall@5 z 0,924 na 0,894, recall@40 z 0,956 na 0,926, MRR z 0,806 na 0,792 a
zavře práh o jednu odpovědnou otázku víc (33 → 32 ze 34). Soubory
`data/processed/eval/rerank-40.json` a `rerank-24.json` jsou to A/B.

**Zmenšovat dávku hodnocení.** Měřeno na pěti otázkách: 20×2 trvalo 9,5 s,
10×4 8,5 s, 8×5 9,4 s — latence je per volání, ne per kandidát. A **29 z 200
známek se pohnulo**, protože dávka je srovnávací množina, v níž model hodnotí.

**Hodnotit adaptivně jen prvních 20 a druhých 20 „jen když je potřeba".**
Ušetřilo by to na snadných otázkách a riskovalo přesně u typů, které jsou už
teď nejslabší: `multi` má recall@5 **0,25** a `annex` 0,875. Úryvek, který
najde jen fulltext — a typicky to je právě příloha, protože nemá vektor — sedí
ve fúzním pořadí nízko, tedy v té druhé dvacítce.

**Zlevňovat odpovídající model první.** Je to 13 % ceny otázky a 100 %
viditelné kvality: citace, odmítnutí, rozpory. Až úplně nakonec a jen s
`eval_answers.py` (dnes 28 answered / 4 partial / 2 insufficient /
6 no_evidence, 72 ze 78 vět prošlo kontrolou citací, 0 nepravdivých odpovědí).

**Explicitní context caching.** Instrukce hodnotitele má 405 tokenů, odpovídací
934 a extrakční schéma 1 214 — pod praktickým minimem pro cached content, a
proti 26 tis. tokenů vstupu marginální.

**Měnit dimenze embeddingu.** `explanation.md:409`: účtuje se za vstupní tokeny,
ne za dimenze. Nezlevní to nic a 1536 je dáno stropem HNSW indexu (nejvýš 2000).

**Měnit extrakční model „na zkoušku".** Je součástí `pipeline_config()`, takže
změna re-extrahuje celý korpus **a** kvůli `summary` v prefixu ho i
přeembedduje. Jeden experiment = ~50 Kč.

---

## 7. Souhrn

Při dnešní ceně 0,82 Kč za studenou otázku:

| krok | úspora / otázku | riziko | čím ověřit |
| --- | ---: | --- | --- |
| 1) přečíst `usage_metadata` | 0 | žádné | nic, je to zdarma |
| 2) thinking u hodnotitele | 0,17–0,28 Kč | známky se mohou pohnout | `eval_retrieval.py` |
| 3) lite hodnotitel | až ~0,42 Kč | práh, schopnost mlčet | `eval_retrieval.py`, 2 běhy |
| 4) fingerprint na dokument | 0 (ale ~11 Kč za ingest) | žádné | unit test |
| 5) zkrátit text kandidátů | ~0,25 Kč | otázky typu `exact` | `eval_retrieval.py` |

Body 2 a 3 dohromady jsou **cesta z 0,82 Kč na ~0,2 Kč, aniž by se dotkly
odpovídajícího modelu** — tedy aniž by se změnilo cokoli, co uživatel čte.

Na straně ingestu (~50 Kč za plný přeběh) je jediná bezriziková položka **batch
pro celokorpusové přeběhy, tedy ~25 Kč**, a jediná strukturální je vyhození
`summary` z embedding prefixu, kterou se vyplatí přivěsit k usazení schématu.

Všechno dohromady a zaokrouhleně: **otázka čtyřikrát levnější, přeběh korpusu
dvakrát** — za cenu dvou až tří eval běhů, které to ověří.
