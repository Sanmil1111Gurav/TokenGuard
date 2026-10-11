import logging
import time
from contextlib import contextmanager
from rich.console import Console
from rich.logging import RichHandler

console = Console()

# Configure logging using RichHandler
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)]
)

logger = logging.getLogger("TokenGuard")

def get_logger(name: str = None):
    """Get the standard TokenGuard logger."""
    if name:
        return logging.getLogger(f"TokenGuard.{name}")
    return logger

@contextmanager
def log_step(step_name: str):
    """Context manager to measure and log the execution time of a step."""
    logger.info(f"[bold cyan]Starting {step_name}...[/bold cyan]", extra={"markup": True})
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.info(
            f"[bold green]Finished {step_name} in {elapsed:.2f}s[/bold green]",
            extra={"markup": True}
        )
