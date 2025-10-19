"""Rate limiting functionality for respectful server interaction."""

import time


class RateLimiter:
    """Rate limiter with adaptive and fixed rate modes."""

    def __init__(self, fixed_rate: float | None = None, base_delay: float = 0.5):
        """Initialize the rate limiter.

        Args:
            fixed_rate: Fixed rate in requests per minute (None for adaptive mode)
            base_delay: Base delay in seconds for adaptive mode
        """
        self.fixed_rate = fixed_rate
        self.base_delay = base_delay
        self.last_request_time = 0.0
        self.consecutive_errors = 0
        self.max_backoff = 30.0  # Maximum backoff delay in seconds

        if fixed_rate:
            self.delay_between_requests = 60.0 / fixed_rate
        else:
            self.delay_between_requests = base_delay

    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.delay_between_requests:
            sleep_time = self.delay_between_requests - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def handle_success(self):
        """Handle a successful request (adaptive mode only)."""
        if not self.fixed_rate:
            # Gradually reduce delay on success
            self.consecutive_errors = 0
            self.delay_between_requests = max(
                self.base_delay, self.delay_between_requests * 0.9
            )

    def handle_error(self, status_code: int | None = None):
        """Handle a request error with exponential backoff.

        Args:
            status_code: HTTP status code of the error
        """
        if not self.fixed_rate:
            self.consecutive_errors += 1

            # More aggressive backoff for rate limiting errors
            if status_code in [429, 503]:
                backoff_multiplier = 2.0
            else:
                backoff_multiplier = 1.5

            # Exponential backoff
            backoff_delay = self.base_delay * (
                backoff_multiplier**self.consecutive_errors
            )
            self.delay_between_requests = min(backoff_delay, self.max_backoff)

            print(
                f"Rate limiting: backing off to {self.delay_between_requests:.1f}s delay"
            )

    def get_current_rate(self) -> float:
        """Get current effective rate in requests per minute.

        Returns:
            float: Current rate in requests per minute
        """
        if self.delay_between_requests <= 0:
            return float("inf")
        return 60.0 / self.delay_between_requests
