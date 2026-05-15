# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Test Feedback Notification Agent** - an AI agent system that analyzes test failure logs, identifies the responsible person, and sends Feishu (飞书) notifications to them. The agent uses an LLM to dynamically plan which analysis capabilities to invoke based on the input.

## Architecture

### Core Agent (`agent/test_feedback_agent.py`)
The `TestFeedbackAgent` is the main entry point. It uses an LLM to decide which capabilities to invoke, then executes them in sequence. The agent maintains memory of the current analysis state and iteration history.

### Agent Sub-modules
- **`agent/base.py`** - Abstract `AgentBase` class
- **`agent/memory/memory.py`** - Two-memory system:
  - `ContextMemory`: current step, confidence level, LLM conversation log
  - `IterationMemory`: history of attempts with evidence and success/failure
- **`agent/planning/planner.py`** - Default pipeline: situation_analysis → log_localization → owner_identification → feishu_notification
- **`agent/execution/executor.py`** - Orchestrates plan execution (alternative to Agent-direct execution)
- **`agent/reflection/reflector.py`** - Adaptive reflection that only relies on actually executed capabilities for confidence calculation

### Capabilities (analyzers)
Each capability implements `execute(situation, failed_log, memory)` and stores results in memory's iteration history.

- **`capabilities/situation_analysis/analyzer.py`** - Analyzes test scenario: extracts command, expected_action, unexpected_incident, possible_modules, bug_hint
- **`capabilities/log_localization/locator.py`** - Deep log analysis: extracts error_type, failed_module, failed_component, root_cause
- **`capabilities/owner_identification/identifier.py`** - Maps bug_module to owner using `ModuleOwnerTable` (xlsx); falls back to LLM extraction
- **`capabilities/feishu_notification/notifier.py`** - Sends Feishu text message to owner

### Integrations
- **`integrations/llm_client.py`** - OpenAI-compatible LLM client (supports MiniMax, Azure, etc. via `base_url`). Used for planning and JSON extraction.
- **`integrations/feishu_client.py`** - Feishu开放平台 client for sending messages via `im/v1/messages` API
- **`integrations/module_owner_table.py`** - Reads `data/module_owner_mapping.xlsx` to map module IDs to owner info (name, open_id, email, phone, department)
- **`integrations/config_manager.py`** - Loads `.env` config via Pydantic models (`FeishuConfig`, `LLMConfig`)

### Valid Module IDs
When extracting or validating bug modules, only these are valid:
```
rejection_classifier, intent_classifier, instruction_rewriter, command_store,
parameter_extractor, protocol_builder, emqx_client
```

## Running Tests

```bash
python tests/unit/test_llm_client.py
python tests/unit/test_feishu_client.py
```

## Debug / Demo Scripts

```bash
python debug_agent.py          # Minimal test with Agent-direct execution
python debug_robot_scenario.py # Full robot pipeline scenario test
```

## Environment Variables (`.env`)

```
OPENAI_API_KEY=<key>
OPENAI_BASE_URL=https://api.minimaxi.com/v1  # or OpenAI/Azure endpoint
OPENAI_MODEL=MiniMax-M2.7
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_OPEN_BASE_URL=https://open.feishu.cn
MODULE_OWNER_TABLE=data/module_owner_mapping.xlsx
```

## Design Notes

- The Agent uses **LLM-driven planning** to decide which capabilities to run (not a fixed pipeline)
- Results flow through `memory.iteration.attempts` so later capabilities can read earlier results
- **Auto-chaining**: If a capability finds a `bug_module` but `owner_identification` wasn't run, the agent auto-invokes it. Similarly for `feishu_notification` if `owner_open_id` is available
- LLM responses are parsed via multiple JSON extraction strategies (direct parse → markdown block → regex search)
- The xlsx owner table is read-only at startup; call `reload_table()` to refresh
