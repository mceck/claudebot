import asyncio
import shlex

from claudebot.tools.json_models import ClaudeAuthResponse
from claudebot.tools.shell import run_command
from claudebot.settings import settings


class Claude:
    cwd: str
    process: asyncio.subprocess.Process | None

    def __init__(self, cwd: str):
        self.cwd = cwd
        self.process = None

    @staticmethod
    async def check_login():
        ret_code, output = await run_command(
            "claude --dangerously-skip-permissions -p auth status"
        )
        if ret_code != 0:
            raise Exception(f"Failed to check login status: {output}")
        return ClaudeAuthResponse.model_validate_json(output)
        

    async def send(
        self, message: str, resume_session: bool = False, plan_mode: bool = False
    ) -> tuple[int, str]:
        escaped_message = shlex.quote(message)
        cmd = f"claude --dangerously-skip-permissions"
        if settings.MODEL:
            cmd += f" --model {settings.MODEL}"
        if settings.EFFORT:
            cmd += f" --effort {settings.EFFORT}"
        if plan_mode:
            cmd += f" --permission-mode plan"
        if resume_session:
            cmd += f" -c"
        cmd += f" -p {escaped_message}"
        self.process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await self.process.communicate()
        if stderr:
            print(
                f"Error from Claude process: {stderr.decode('utf-8', errors='ignore')}"
            )
        res = stdout.decode("utf-8", errors="ignore").strip()
        return self.process.returncode or 0, res

    async def kill(self):
        if self.process:
            self.process.kill()
            await self.process.wait()
            self.process = None
