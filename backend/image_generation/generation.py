import asyncio
import time
from typing import List, Union

from image_generation.replicate import (
    DEFAULT_IMAGE_MODEL,
    ReplicateImageModel,
    call_replicate,
)
from logging_config import get_logger

logger = get_logger("image_generation")


REPLICATE_BATCH_SIZE = 20
REPLICATE_IMAGE_MODEL: ReplicateImageModel = DEFAULT_IMAGE_MODEL


async def process_tasks(
    prompts: List[str],
    api_key: str,
    _base_url: str | None,
    _model: str,
) -> List[Union[str, None]]:
    start_time = time.time()
    results: list[str | BaseException | None]
    results = []
    for i in range(0, len(prompts), REPLICATE_BATCH_SIZE):
        batch = prompts[i : i + REPLICATE_BATCH_SIZE]
        tasks = [generate_image_replicate(p, api_key) for p in batch]
        results.extend(await asyncio.gather(*tasks, return_exceptions=True))
    end_time = time.time()
    generation_time = end_time - start_time
    logger.info("image generation batch complete", extra={"seconds": round(generation_time, 2), "count": len(prompts)})

    processed_results: List[Union[str, None]] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("image generation task failed", extra={"error": type(result).__name__})
            processed_results.append(None)
        else:
            processed_results.append(result)

    return processed_results


async def generate_image_replicate(prompt: str, api_key: str) -> str:
    replicate_input: dict[str, str | int | float | bool]
    if REPLICATE_IMAGE_MODEL == "flux_2_klein":
        replicate_input = {
            "prompt": prompt,
            "aspect_ratio": "1:1",
            "output_format": "png",
        }
    else:
        replicate_input = {
            "prompt": prompt,
            "width": 1024,
            "height": 1024,
            "go_fast": False,
            "output_format": "png",
            "guidance_scale": 0,
            "num_inference_steps": 8,
        }

    return await call_replicate(
        replicate_input,
        api_key,
        model=REPLICATE_IMAGE_MODEL,
    )
