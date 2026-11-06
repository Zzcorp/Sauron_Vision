# The operator's plan for the charts, the signals and the rest (2026-11-06)

He asked for "un plan de magnification / amélioration pur et dur des charts et des signaux etc." and is detailing it point by point. His words are kept verbatim; the notes under each are ours. Nothing is built from this file until he has confirmed the plan cut into steps, except point 2, which rides `claude/railfilters` (the same popups).

## His points

1. "ameliore le design peu etre, plus haut de gamme, elegant"
   - His reference (asked): "un smart melange de bloomberg et trading view sous sauron" — a smart blend of Bloomberg (dense, data-first, terminal discipline) and TradingView (clean charts, fluid interaction), in Sauron's own identity.
   - Still to ask: which screens first; dark/light; phone/desktop.
2. "quand on click sur un signal faire que le dessous de popup soit mieux placer pour voir le contenu dessous, faire que scroll possible sur click de ce dernier par en hover etc"
   - Notes: the popups that open from a signal and from the headband open on click/tap and stay open; they sit inside the viewport with a scrolling body; hover is never the only way. Folded into `claude/railfilters` (section F of its design).
3. "ameliorer responsive complet etc"
   - Notes: every page usable at phone and tablet widths (no horizontal scroll, touch targets, the band, the rail, the chart, the ticket, the positions).
4. "Ajouter rectangle, lignes et design de ces derniers etc... comme trading view in sauron style, in the end... please"
   - Notes: chart drawing tools (rectangles, trend and horizontal lines, and their styles: colour, width, dash, fill), saved per chart, in Sauron's style. "in the end" may mean last in order; to confirm.

## Related work already in flight

- `claude/railfilters`: the signal rail without a hidden cap, a real lifecycle, headband filters for the signals and the watchlist, and point 2.
- The eToro-grade live feed (design in progress): eToro's own bid/ask on screen about as fast as eToro's app, harmless source switching.
