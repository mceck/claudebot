import asyncio
import json
import os
import signal
import shlex
import uuid

from codebot.tools.json_models import ClaudeAuthResponse
from codebot.tools.shell import run_command
from codebot.settings import settings


class Claude:
    cwd: str
    process: asyncio.subprocess.Process | None
    session_uuid: str
    prompt: str | None

    def __init__(self, cwd: str):
        self.cwd = cwd
        self.process = None
        self.session_uuid = str(uuid.uuid4())
        self.prompt = None

    @staticmethod
    async def check_login():
        ret_code, output = await run_command(
            "claude --dangerously-skip-permissions -p auth status"
        )
        if ret_code != 0:
            raise Exception(f"Failed to check login status: {output}")
        return ClaudeAuthResponse.model_validate_json(output)

    async def send(
        self, message: str, resume_session: bool = False, plan_mode: bool = False,
        on_event=None, resume_session_id: str | None = None,
    ) -> tuple[int, str]:
        self.prompt = message
        escaped_message = shlex.quote(message)
        cmd = f"claude --dangerously-skip-permissions"
        from codebot.tools.context import ctx
        model = ctx.selected_model or settings.MODEL
        if model:
            cmd += f" --model {model}"
        if settings.EFFORT:
            cmd += f" --effort {settings.EFFORT}"
        if plan_mode:
            cmd += f" --permission-mode plan"
        if resume_session_id:
            cmd += f" -r {shlex.quote(resume_session_id)}"
        elif resume_session:
            cmd += f" -c"
        cmd += f" --output-format stream-json --verbose -p {escaped_message}"
        self.process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=10 * 1024 * 1024,  # 10MB buffer limit
        )

        final_result = ""
        claude_session_id = None

        # Drain stderr in background to avoid deadlock
        async def _drain_stderr():
            data = await self.process.stderr.read()
            if data:
                print(
                    f"Error from Claude process: {data.decode('utf-8', errors='ignore')}"
                )

        stderr_task = asyncio.create_task(_drain_stderr())

        while True:
            try:
                line = await self.process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError) as e:
                print(f"Stream read error (skipping): {e}")
                if on_event:
                    try:
                        await on_event(
                            session_uuid=self.session_uuid,
                            claude_session_id=claude_session_id,
                            event_type="assistant",
                            content="[ERR] stream read error, continuing...",
                        )
                    except Exception:
                        pass
                continue
            if not line:
                break
            line_str = line.decode("utf-8", errors="ignore").strip()
            if not line_str:
                continue
            try:
                event = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            try:
                event_type = event.get("type", "unknown")
                if not claude_session_id:
                    claude_session_id = event.get("session_id")

                if event_type == "assistant":
                    msg = event.get("message", {})
                    content_blocks = msg.get("content", [])
                    texts = []
                    tools = []
                    for block in content_blocks:
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            key = ""
                            if tool_name in ("Read", "Edit", "Write"):
                                key = tool_input.get("file_path", "")
                            elif tool_name == "Glob":
                                key = tool_input.get("pattern", "")
                            elif tool_name == "Bash":
                                key = tool_input.get("command", "")[:80]
                            elif tool_name == "Grep":
                                key = tool_input.get("pattern", "")
                            tools.append(f"{tool_name}: {key}" if key else tool_name)

                    if on_event:
                        try:
                            if texts:
                                text_content = "\n".join(texts)[:500]
                                await on_event(
                                    session_uuid=self.session_uuid,
                                    claude_session_id=claude_session_id,
                                    event_type="assistant",
                                    content=text_content,
                                )
                            if tools:
                                tools_content = "\n".join(tools)
                                await on_event(
                                    session_uuid=self.session_uuid,
                                    claude_session_id=claude_session_id,
                                    event_type="tool_use",
                                    content=tools_content,
                                )
                        except Exception as e:
                            print(f"Error in on_event callback: {e}")

                elif event_type == "result":
                    final_result = event.get("result", "")
                    if on_event:
                        try:
                            cost = event.get("cost_usd")
                            duration = event.get("duration_ms")
                            num_turns = event.get("num_turns")
                            meta_parts = []
                            if cost is not None:
                                meta_parts.append(f"${cost:.4f}")
                            if duration is not None:
                                meta_parts.append(f"{duration / 1000:.1f}s")
                            if num_turns is not None:
                                meta_parts.append(f"{num_turns} turns")
                            meta = " | ".join(meta_parts)
                            await on_event(
                                session_uuid=self.session_uuid,
                                claude_session_id=claude_session_id,
                                event_type="result",
                                content=meta or "done",
                            )
                        except Exception as e:
                            print(f"Error in on_event callback: {e}")
            except Exception as e:
                print(f"Error processing event (skipping): {e}")
                if on_event:
                    try:
                        await on_event(
                            session_uuid=self.session_uuid,
                            claude_session_id=claude_session_id,
                            event_type="assistant",
                            content="[ERR] event processing error, continuing...",
                        )
                    except Exception:
                        pass

        await stderr_task
        await self.process.wait()
        return self.process.returncode or 0, final_result.strip()

    async def kill(self):
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            self.process = None
