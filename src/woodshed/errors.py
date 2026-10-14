"""Errors raised by woodshed: expected failures, with a message meant for the user.

The command line will catch WoodshedError and map it to an exit code (not implemented yet).
"""


class WoodshedError(Exception):
    """Base class: an expected failure with a message meant for the user."""


class AudioError(WoodshedError):
    """The file is missing, unreadable, or not audio."""


class BeatError(WoodshedError):
    """No usable beat grid, or no musical content."""


class StemsError(WoodshedError):
    """Stem separation or model loading failed."""


class MissingExtra(WoodshedError):
    """An optional feature needs the stems extra."""
