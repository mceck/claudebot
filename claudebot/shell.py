import asyncio

async def run_command(cmd: str, cwd: str = ".") -> tuple[int, str]:
    process = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    output = stdout.decode("utf-8", errors="ignore") + stderr.decode("utf-8", errors="ignore")
    return process.returncode or 0, output