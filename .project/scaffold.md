Correctly segregate project structure into this:

- `agent`
  - LLM-driven reasoning and decision modules

- `logic`
  - deterministic domain logic, rules, scoring, and evaluation
  - includes `logic/evaluations/` for deterministic LLM output quality checks and retry/fallback policy

- `tools`
  - provider integrations, fetchers, and external adapters

- `workflows`
  - orchestrators that sequence agents, logic, tools, and memory
  - includes `workflows/dashboard/` for dashboard serving and UI-related workflow endpoints

- `memory`
  - persistence, state, database helpers, watchlists, and stored artifacts

- `prompts`
  - prompt templates used by LLM-based agents

- `business_case`
  - PRD, business case, user research, and other business/product context

- `.project`
  - technical docs, templates, metadata, and project scaffolding references
  - includes `.project/templates/` for reusable project bootstrap files
