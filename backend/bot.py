from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.runner.types import SmallWebRTCRunnerArguments
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from config import settings
from services.generation import generate_model
from slicer_service import process_model

SYSTEM_PROMPT = (
    "You extract concise 3D generation prompts from user speech. "
    "Return ONLY JSON with a single key 'prompt'. "
    "No markdown, no extra text."
)


class TranscriptForwarder(FrameProcessor):
    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            await self.push_frame(
                OutputTransportMessageFrame(
                    {
                        "type": "transcript",
                        "text": frame.text,
                        "is_final": False,
                    }
                )
            )
        elif isinstance(frame, TranscriptionFrame):
            await self.push_frame(
                OutputTransportMessageFrame(
                    {
                        "type": "transcript",
                        "text": frame.text,
                        "is_final": True,
                    }
                )
            )

        await self.push_frame(frame, direction)


class IntentProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._buffer = ""
        self._lock = asyncio.Lock()

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMTextFrame):
            self._buffer += frame.text
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self._handle_llm_response(self._buffer)
            self._buffer = ""

        await self.push_frame(frame, direction)

    async def _handle_llm_response(self, text: str) -> None:
        async with self._lock:
            prompt = _extract_prompt(text)
            if not prompt:
                await self.push_frame(
                    OutputTransportMessageFrame(
                        {"type": "error", "message": "No prompt extracted."}
                    )
                )
                return

            await self.push_frame(
                OutputTransportMessageFrame(
                    {"type": "intent", "prompt": prompt}
                )
            )

            await self.push_frame(
                OutputTransportMessageFrame(
                    {"type": "status", "stage": "generating"}
                )
            )
            generation = await generate_model(prompt)

            await self.push_frame(
                OutputTransportMessageFrame(
                    {
                        "type": "model",
                        "prompt": prompt,
                        "glb_url": generation.glb_url,
                        "provider": generation.provider,
                    }
                )
            )

            await self.push_frame(
                OutputTransportMessageFrame(
                    {"type": "status", "stage": "slicing"}
                )
            )
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, process_model, generation.glb_url)

            await self.push_frame(
                OutputTransportMessageFrame(
                    {
                        "type": "gcode",
                        "job_id": result.job_id,
                        "gcode_url": f"/artifacts/{result.job_id}/{result.gcode_path.name}",
                        "stl_url": f"/artifacts/{result.job_id}/{result.stl_path.name}",
                        "glb_url": f"/artifacts/{result.job_id}/{result.glb_path.name}",
                    }
                )
            )


def _extract_prompt(text: str) -> Optional[str]:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            value = payload.get("prompt")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except json.JSONDecodeError:
        pass

    cleaned = text.strip()
    return cleaned or None


async def bot(runner_args):
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise ValueError("This bot expects SmallWebRTC runner arguments.")

    transport = SmallWebRTCTransport(
        runner_args.webrtc_connection,
        TransportParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000),
    )

    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY is required for STT")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for LLM")

    stt = DeepgramSTTService(api_key=settings.deepgram_api_key)
    llm = OpenAILLMService(api_key=settings.openai_api_key, model=settings.openai_model)

    context = OpenAILLMContext()
    context.add_message({"role": "system", "content": SYSTEM_PROMPT})
    aggregators = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            TranscriptForwarder(),
            aggregators.user(),
            llm,
            IntentProcessor(),
            aggregators.assistant(),
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
        ),
        cancel_on_idle_timeout=False,
    )
    runner = PipelineRunner()
    await runner.run(task)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
