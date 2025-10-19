"""Color themes for the TUI interface."""

from textual.theme import Theme

# Dark theme (default)
DARK_THEME = Theme(
    {
        "header": "bold white on blue",
        "statistics": "white on black",
        "progress": "green on black",
        "activity.success": "green on black",
        "activity.error": "red on black",
        "activity.skip": "yellow on black",
        "current_download": "cyan on black",
        "status.downloading": "green on black",
        "status.paused": "yellow on black",
        "status.stopped": "red on black",
    }
)

# Light theme
LIGHT_THEME = Theme(
    {
        "header": "bold black on white",
        "statistics": "black on white",
        "progress": "green on white",
        "activity.success": "green on white",
        "activity.error": "red on white",
        "activity.skip": "yellow on white",
        "current_download": "blue on white",
        "status.downloading": "green on white",
        "status.paused": "yellow on white",
        "status.stopped": "red on white",
    }
)
