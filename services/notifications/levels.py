from enum import Enum


class NotificationLevel(Enum):
    """Broad category a notification falls into. Channels use this to pick
    an icon/tone — e.g. the system channel maps FAILURE to a warning icon,
    SUCCESS/INFO to an information icon."""
    INFO = "info"
    SUCCESS = "success"
    FAILURE = "failure"
