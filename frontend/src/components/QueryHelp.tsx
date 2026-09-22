import { HelpCircle } from 'lucide-react'

// What a query may contain beyond plain words. Prefixes are parsed by
// search_filters.py, the operators by websearch_to_tsquery; both lists mirror
// what those two accept, so a change there belongs here too.

const PREFIXES: [string, string, string][] = [
  ['autor:', 'autora', 'autor:Bičík'],
  ['org:', 'organizaci', 'org:GEOtest'],
  ['klient:', 'objednatele', 'klient:Roudno'],
  ['obec:', 'obec', 'obec:Lednice'],
  ['lokalita:', 'lokalitu', 'lokalita:Chodov'],
  ['typ:', 'typ průzkumu', 'typ:hydrogeologický'],
  ['od: / do:', 'datum zprávy', 'od:2019 do:2023'],
  ['druh:', 'tělo zprávy, nebo přílohy', 'druh:příloha sonda S-2'],
]

const OPERATORS: [string, string, string][] = [
  ['hladina vody', 'úryvek musí obsahovat všechna slova, v libovolném pořadí', 'najde i „voda … její hladina“'],
  ['"hladina podzemní vody"', 'slova musí stát přesně za sebou', 'přesná fráze'],
  ['hladina -radon', 'úryvky se slovem „radon“ vyřadí', 'hladina, ale ne u radonu'],
  ['vrt or sonda', 'stačí jedno z těch slov', 'vrty i sondy'],
]

function Table({ rows, head }: { rows: [string, string, string][]; head: [string, string, string] }) {
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-slate-500">
        <tr>
          {head.map((cell) => (
            <th key={cell} className="pb-1 pr-3 font-medium">
              {cell}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(([code, meaning, example]) => (
          <tr key={code} className="border-t border-slate-100 align-top">
            <td className="whitespace-nowrap py-1 pr-3">
              <code className="rounded bg-slate-100 px-1 text-brand-800">{code}</code>
            </td>
            <td className="py-1 pr-3 text-slate-700">{meaning}</td>
            <td className="py-1 text-slate-500">{example}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** A hint box that opens the full query syntax on hover or keyboard focus. */
export function QueryHelp() {
  return (
    <span className="group relative">
      <button
        type="button"
        aria-describedby="query-help"
        className="inline-flex items-center gap-1.5 rounded-md border border-brand-200 bg-brand-50 px-2 py-1 text-xs text-brand-800 hover:border-brand-400 focus:border-brand-500 focus:outline-none"
      >
        <HelpCircle className="h-3.5 w-3.5" />
        <span>
          Tip: <code>autor:Poul</code>, <code>"přesná fráze"</code>, <code>-slovo</code>, <code>a or b</code>
        </span>
      </button>
      <div
        id="query-help"
        role="tooltip"
        className="invisible absolute right-0 top-full z-30 mt-2 w-[36rem] max-w-[calc(100vw-2rem)] space-y-3 rounded-lg border border-slate-200 bg-white p-4 text-left opacity-0 shadow-lg transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        <section>
          <h3 className="text-sm font-semibold text-brand-900">1. Předpona s dvojtečkou omezí, ve kterých posudcích se hledá</h3>
          <p className="mb-2 mt-1 text-xs text-slate-600">
            Slovo s dvojtečkou se nehledá v textu, vybere dokumenty. Stačí část jména: <code>autor:Poul</code> najde i „RNDr. Mgr. Ivan Poul,
            Ph.D.“. Hodnotu s mezerou dejte do uvozovek: <code>autor:"Ivan Poul"</code>. Je to totéž co panel Filtry a platí ve všech režimech.
          </p>
          <Table rows={PREFIXES} head={['předpona', 'filtruje', 'příklad']} />
        </section>
        <section>
          <h3 className="text-sm font-semibold text-brand-900">2. Uvozovky, mínus a „or“ řídí hledání slov</h3>
          <p className="mb-2 mt-1 text-xs text-slate-600">
            Skloňování platí i tady: <code>vrty</code> najde „vrtů“ i „vrtech“. Pravidla platí jen pro Fulltext; sémantické hledání porovnává
            význam celé věty a uvozovky ani mínus ho neovlivní.
          </p>
          <Table rows={OPERATORS} head={['zápis', 'význam', 'příklad']} />
        </section>
        <p className="border-t border-slate-100 pt-2 text-xs text-slate-600">
          Kombinovat se dá všechno: <code className="rounded bg-slate-100 px-1 text-brand-800">obec:Lednice "podzemní voda" -radon</code>
        </p>
      </div>
    </span>
  )
}
