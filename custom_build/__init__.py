"""custom_build: one Hermes plugin (ARCHITECTURE.md section 1).

So far it holds only the failure catalog (`failures`), so `register()` has nothing to register.
"""


def register(ctx) -> None:
    """Called by Hermes on each load of the plugin. Registers nothing yet."""
