# Architecture

This document describes the current high-level architecture of the Investment Analyzer project.

## System Overview

```mermaid
flowchart TB
    subgraph Inputs["External Inputs"]
        FH["Finnhub API"]
        SEC["SEC EDGAR / XBRL"]
        NEWS["Google News RSS"]
        REDDIT["Reddit API (optional)"]
        YF["yfinance"]
        CLAUDE["Claude Models"]
    end

    subgraph Memory["memory/"]
        DB["database.py"]
        WL["watchlist.json"]
        SQLITE["investment_analyzer.db"]
    end

    subgraph Tools["tools/"]
        FHCLIENT["finnhub_client.py"]
        EDGAR["edgar_client.py"]
        XBRL["sec_xbrl_client.py"]
        NEWSCLIENT["news_client.py"]
        REDDITCLIENT["reddit_client.py"]
    end

    subgraph Logic["logic/"]
        SCREENER["screener.py"]
        subgraph Evals["evaluations/"]
            RESEVAL["researcher_eval.py"]
            CORREVAL["self_corrector_eval.py"]
            PORTEVAL["portfolio_manager_eval.py"]
        end
    end

    subgraph Agents["agent/"]
        RESEARCHER["researcher.py"]
        CORRECTOR["self_corrector.py"]
        PM["portfolio_manager.py"]
    end

    subgraph Workflows["workflows/"]
        DAILY["run_daily.py"]
        WEEKLY["run_weekly.py"]
        DASH["dashboard/server.py"]
    end

    subgraph Prompts["prompts/"]
        THESIS["thesis_prompt.txt"]
        CORRP["correction_prompt.txt"]
        PORTP["portfolio_prompt.txt"]
    end

    WL --> DB
    DB --> SQLITE

    FH --> FHCLIENT
    SEC --> EDGAR
    SEC --> XBRL
    NEWS --> NEWSCLIENT
    REDDIT --> REDDITCLIENT
    YF --> PM
    YF --> DASH
    CLAUDE --> RESEARCHER
    CLAUDE --> CORRECTOR
    CLAUDE --> PM

    FHCLIENT --> SCREENER
    XBRL --> SCREENER

    SCREENER --> DAILY
    SCREENER --> WEEKLY

    FHCLIENT --> RESEARCHER
    EDGAR --> RESEARCHER
    NEWSCLIENT --> RESEARCHER
    REDDITCLIENT --> RESEARCHER
    THESIS --> RESEARCHER
    RESEVAL --> RESEARCHER

    EDGAR --> CORRECTOR
    NEWSCLIENT --> CORRECTOR
    CORRP --> CORRECTOR
    CORREVAL --> CORRECTOR

    PORTP --> PM
    PORTEVAL --> PM

    DB --> DAILY
    DB --> WEEKLY
    DB --> PM
    DB --> DASH

    DAILY --> RESEARCHER
    DAILY --> PM
    DAILY --> DB

    WEEKLY --> RESEARCHER
    WEEKLY --> CORRECTOR
    WEEKLY --> DB

    DASH --> DB
    DASH --> SQLITE
```

## Folder Responsibilities

- `agent/`
  - LLM-driven reasoning and decision modules.

- `logic/`
  - Deterministic domain logic such as ranking, validation, and evaluation.

- `logic/evaluations/`
  - Deterministic quality checks for agent outputs.
  - These modules decide whether output is acceptable, should be retried, or should degrade to fallback behavior.

- `tools/`
  - Provider-specific adapters and low-level fetchers.

- `workflows/`
  - Orchestration entrypoints that sequence tools, logic, agents, and persistence.

- `memory/`
  - Persistent state and storage.

- `prompts/`
  - Prompt templates used by LLM-based agents.

## Daily Workflow

```mermaid
flowchart LR
    A["workflows/run_daily.py"] --> B["logic/screener.py"]
    B --> C["agent/researcher.py"]
    C --> D["agent/portfolio_manager.py"]
    D --> E["memory/database.py"]
```

### Daily Flow Notes

- `run_daily.py` loads the active watchlist from SQLite-backed memory.
- The screener ranks candidates using deterministic factors from Finnhub and SEC XBRL.
- The researcher generates structured thesis output for non-held names.
- The portfolio manager uses Claude to propose buys and sells, then applies deterministic validation.
- Portfolio state, trades, and snapshots are persisted through `memory/database.py`.

## Weekly Workflow

```mermaid
flowchart LR
    A["workflows/run_weekly.py"] --> B["logic/screener.py"]
    B --> C["agent/researcher.py"]
    C --> D["agent/self_corrector.py"]
    D --> E["memory/database.py"]
```

### Weekly Flow Notes

- `run_weekly.py` screens the watchlist and researches the shortlisted names.
- `self_corrector.py` compares current outputs against prior snapshots and logs thesis drift.
- Corrections and updated snapshots are written back to SQLite.

## Evaluation Layer

The evaluation layer exists to reduce the risk of low-quality LLM outputs inside orchestrated workflows.

Current evaluation modules:

- `logic/evaluations/researcher_eval.py`
  - checks researcher output shape and minimum content quality

- `logic/evaluations/self_corrector_eval.py`
  - checks correction output validity and required fields

- `logic/evaluations/portfolio_manager_eval.py`
  - checks trade-decision schema and minimum structural quality

### Evaluation Pattern

```mermaid
flowchart LR
    A["Agent produces output"] --> B["Deterministic evaluator runs"]
    B --> C{"Pass?"}
    C -- Yes --> D["Accept output"]
    C -- No --> E["Retry once or fallback"]
```

The evaluators belong in `logic/evaluations/` because they are deterministic policy and quality-control code, not LLM agents themselves.

## Data Flow Summary

- External providers feed data into `tools/`.
- `logic/` turns raw provider data into deterministic scores and validations.
- `agent/` uses prompts plus external context to produce LLM-driven decisions.
- `workflows/` coordinate when each step runs and what happens after each result.
- `memory/` persists outputs and state so the dashboard and future workflows can inspect history.

## Entrypoints

```bash
python3 -m memory.database
python3 -m workflows.run_daily --force
python3 -m workflows.run_weekly
python3 -m workflows.dashboard.server
```
