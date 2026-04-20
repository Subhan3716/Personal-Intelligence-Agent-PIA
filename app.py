from __future__ import annotations

import logging
import os
import warnings


def _quiet_runtime() -> None:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    logging.basicConfig(level=logging.CRITICAL, force=True)
    logging.getLogger().setLevel(logging.CRITICAL)

    warnings.filterwarnings("ignore")
    warnings.filterwarnings("ignore", module=r"transformers\..*")
    warnings.filterwarnings("ignore", module=r"PIL\..*")
    warnings.filterwarnings("ignore", message=r".*TypedStorage is deprecated.*")
    warnings.filterwarnings("ignore", message=r".*Palette images with Transparency.*")

    noisy_loggers = [
        "PIL",
        "PIL.Image",
        "PIL.PngImagePlugin",
        "streamlit",
        "transformers",
        "sentence_transformers",
        "huggingface_hub",
        "watchdog",
        "urllib3.connectionpool",
        "httpx",
        "googleapiclient.discovery_cache",
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)


_quiet_runtime()

from main import main

if __name__ == "__main__":
    main()
