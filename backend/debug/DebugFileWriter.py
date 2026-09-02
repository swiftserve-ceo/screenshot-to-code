import os
import uuid

from config import DEBUG_DIR, IS_DEBUG_ENABLED
from logging_config import get_logger

logger = get_logger("debug.file_writer")


class DebugFileWriter:
    def __init__(self):
        if not IS_DEBUG_ENABLED:
            return

        try:
            self.debug_artifacts_path = os.path.expanduser(
                f"{DEBUG_DIR}/{str(uuid.uuid4())}"
            )
            os.makedirs(self.debug_artifacts_path, exist_ok=True)
            logger.debug(
                "debug artifacts directory ready", extra={"path": self.debug_artifacts_path}
            )
        except Exception:
            logger.error("failed to create debug directory", exc_info=True)

    def write_to_file(self, filename: str, content: str) -> None:
        try:
            with open(os.path.join(self.debug_artifacts_path, filename), "w") as file:
                file.write(content)
        except Exception:
            logger.error("failed to write debug file", exc_info=True)

    def extract_html_content(self, text: str) -> str:
        return str(text.split("<html>")[-1].rsplit("</html>", 1)[0] + "</html>")
