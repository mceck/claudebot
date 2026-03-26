from codebot.tools.claude import Claude

class Context:
    def __init__(self):
        self.claude_sessions: dict[str, Claude] = {}
        self.current_project: str | None = None
        self.active_streams: set[str] = set()
        self.resume_claude_session_id: dict[str, str] = {}  # project -> claude_session_id
        self.pending_recovery: dict | None = None  # {claude_sid, project, prompt_preview}
        self.pending_queue: dict[str, dict] = {}  # project -> {chat_id, message} awaiting user confirmation
        self.queued_messages: dict[str, dict] = {}  # project -> {chat_id, message} confirmed, waiting to run

    def set_current_project(self, project_name: str):
        self.current_project = project_name

    
ctx = Context()