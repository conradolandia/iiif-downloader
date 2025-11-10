"""Custom progress column classes for Rich progress bars."""

from rich.progress import ProgressColumn
from rich.text import Text


class CompletedTotalColumn(ProgressColumn):
    """Custom column that shows 'Unknown' instead of 'None' when total is None."""

    def render(self, task):
        """Render the completed/total display.

        Args:
            task: The progress task

        Returns:
            Text: Formatted text showing completed/total
        """
        completed = task.completed or 0
        total = task.total
        if total is None:
            return Text(f"{completed}/Unknown", style="bold green")
        return Text(f"{completed}/{total}", style="bold green")


class FixedWidthTextColumn(ProgressColumn):
    """Text column with fixed width to maintain alignment."""

    def __init__(self, width: int = 30, *args, **kwargs):
        """Initialize the fixed-width text column.

        Args:
            width: Fixed width for the column
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
        super().__init__(*args, **kwargs)
        self.width = width

    def render(self, task):
        """Render text with fixed width.

        Args:
            task: The progress task

        Returns:
            Text: Formatted text with fixed width
        """
        text = task.description or ""
        # Truncate or pad to fixed width
        if len(text) > self.width:
            text = text[: self.width - 3] + "..."
        else:
            text = text.ljust(self.width)
        return Text(text, style="bold blue")
