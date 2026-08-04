"""
Strategy notification alerts: entry-signal detection (debounced, off a
strategy's trigger condition), post-entry lifecycle tracking (Target/Stop
Loss/Trailing Exit crossings, running High/Low), and delivery through
services.notifications.

See services/strategy_alerts/engine.py for the evaluation state machine and
the plan this package implements for the full design rationale.
"""
