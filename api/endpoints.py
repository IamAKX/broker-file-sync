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
LMV_SNAPSHOT = "/lmv-snapshot"

HOLIDAYS = "/holidays"
