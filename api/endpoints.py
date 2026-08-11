"""Single source of truth for every backend route path (no leading BASE_URL)."""

LOGIN = "/auth/login"
SIGNUP = "/auth/signup"
REFRESH = "/auth/refresh"
LOGOUT = "/auth/logout"
ME = "/auth/me"
CHANGE_PASSWORD = "/auth/change-password"

DAILY_UPLOAD = "/historic/daily-upload"
AVAILABILITY = "/historic/availability"
SNAPSHOT = "/historic/snapshot"
HISTORIC = "/historic"

LMV_SNAPSHOT_DAILY_UPLOAD = "/lmv-snapshot/daily-upload"
LMV_SNAPSHOT_AVAILABILITY = "/lmv-snapshot/availability"
LMV_SNAPSHOT_SNAPSHOT = "/lmv-snapshot/snapshot"
LMV_SNAPSHOT_RANGE = "/lmv-snapshot/range"
LMV_SNAPSHOT = "/lmv-snapshot"

OPENING_RANGE_DAILY_UPLOAD = "/opening-range/daily-upload"
OPENING_RANGE_AVAILABILITY = "/opening-range/availability"
OPENING_RANGE_SNAPSHOT = "/opening-range/snapshot"
OPENING_RANGE = "/opening-range"

HOLIDAYS = "/holidays"

NOTIFICATIONS_EMAIL_SEND = "/notifications/email/send"
NOTIFICATIONS_EMAIL_TEST = "/notifications/email/test"

STRATEGIES = "/strategies"
STRATEGIES_IMPORT = "/strategies/import"

STRATEGY_SIGNALS = "/strategy-signals"

FORMULA_VARIABLES = "/formula-variables"

SETTINGS = "/settings"

THEME = "/auth/me/theme"
