"""ADE — Autonomous Data Engineer.

An event-driven agent that discovers data sources, builds ETL pipelines,
detects schema/data drift, retrains ML models, monitors production,
optimizes AWS costs, generates documentation, and recovers from failures.

The agent loop lives in ade.agent.orchestrator; planning decisions are
delegated to Claude (via Amazon Bedrock) in ade.agent.planner and validated
against a strict action allowlist before execution.
"""

__version__ = "0.1.0"
