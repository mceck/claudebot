from claudebot.tools.claude import Claude

class Context:
    def __init__(self):
        self.claude_sessions: dict[str, Claude] = {}
        self.current_project: str | None = None

    def set_current_project(self, project_name: str):
        self.current_project = project_name

    
ctx = Context()