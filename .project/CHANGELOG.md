# Changes

This page keeps a simple record of how Investment Analyzer has improved over time.

---

## [2026-02-28] — The System Now Learns From Its Mistakes

- The app now looks back at recent mistakes and uses them to guide future decisions.
- If a sector has had a lot of wrong calls recently, the system becomes more cautious with that sector.
- The app now creates simple "learning hints" from repeated mistakes and feeds those back into future research and portfolio decisions.
- A new **Learning** page shows:
  - where the system has become more cautious
  - what lessons it is currently using
  - how those lessons have changed over time

In plain terms: the system is no longer just reviewing itself. It is now starting to course-correct.

---

## [2026-02-28] — Trades Can Now Be Traced Back To The Original Thesis

- The portfolio system now keeps track of which research thesis was behind each buy.
- When a position is later sold, the app can show the result next to the original thesis, conviction, and catalyst.
- A new section on the Portfolio page now helps answer:
  - what idea led to this trade
  - whether that idea made or lost points
  - which kinds of reasoning are actually working

This makes it easier to judge the quality of the system's decisions over time.

---

## [2026-02-28] — About And Changes Pages Added

- Added an **About** page so anyone can quickly understand what the product does.
- Added a **Changes** page so progress is visible inside the app.

---

## [2026-02-28] — Product Documentation Added

- Wrote a clear product overview.
- Documented the goals, workflows, and future direction of the project.

---

## [2026-02-28] — App Deployed Online

- The app is now live online.
- Startup was improved so the system can initialize itself and keep running on a schedule.
- Data is stored in a persistent way so it is not lost on restart.

---

## [2026-02-27] — Daily Paper Trading Added

- The app can now run a daily paper-trading workflow.
- It reviews current holdings, looks at new ideas, and decides what to buy or sell.
- A portfolio page was added so users can see:
  - current holdings
  - portfolio value over time
  - full trade history

---

## [2026-02-25] — Dashboard Improved

- The dashboard was rebuilt into a faster and more reliable web app.
- Main pages were added for:
  - summary
  - stock detail
  - corrections
  - accuracy
- Charts and table behavior were improved so the app is easier to use.

---

## [2026-02-20] — Weekly Self-Review Added

- The app now reviews its previous weekly stock theses against new information.
- It marks each thesis as:
  - still holding up
  - needing an update
  - or being wrong
- It also records the likely reason a thesis failed.

This is the first step toward a self-correcting system.

---

## [2026-02-15] — AI Researcher Added

- The app can now create stock theses using financial data, filings, and news.
- Each thesis includes:
  - the main idea
  - the main risk
  - a possible catalyst
  - a confidence score

---

## [2026-02-10] — Stock Screener Added

- Built the first version of the stock screener.
- The screener ranks stocks by value and quality instead of using AI.
- Added the main data feeds needed to support research.

---

## [2026-02-05] — Data Foundation Added

- Created the database and the stock watchlist.
- This gave the app a place to store research, corrections, trades, and portfolio history.

---

## [2026-02-01] — Project Started

- Defined the product idea.
- Chose the main technology stack.
- Set up the first version of the project structure.
