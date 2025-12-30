from __future__ import annotations

import asyncio
from typing import Any

from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    OutputTransportMessageFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.aggregators.sentence import SentenceAggregator
from pipecat.runner.types import SmallWebRTCRunnerArguments
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from config import settings
from services.gemini_intent import extract_prompt
from services.generation import generate_model
from slicer_service import process_model


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
        self._lock = asyncio.Lock()

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            await self._handle_user_text(frame.text)

        await self.push_frame(frame, direction)

    async def _handle_user_text(self, text: str) -> None:
        async with self._lock:
            prompt = await extract_prompt(text)
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


async def bot(runner_args):
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise ValueError("This bot expects SmallWebRTC runner arguments.")

    transport = SmallWebRTCTransport(
        runner_args.webrtc_connection,
        TransportParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000),
    )

    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY is required for STT")
    stt = DeepgramSTTService(api_key=settings.deepgram_api_key)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            TranscriptForwarder(),
            SentenceAggregator(),
            IntentProcessor(),
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
