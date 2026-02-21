# ClaudeBot 🤖

A Telegram bot that provides a seamless interface to interact with Claude AI and manage development projects. Control Claude sessions, execute git operations, and manage multiple projects directly from Telegram.

## ✨ Features

- **Claude AI Integration**: Send messages to Claude and receive responses directly in Telegram
- **Project Management**: Switch between multiple projects seamlessly
- **Authentication**: Secure access control with user ID whitelisting

## 🚀 Installation

### Using Docker

Check the `docker-compose.example.yml` file for an example of how to set up the bot with Docker.

### Getting Your Telegram User ID

1. Start a chat with [@userinfobot](https://t.me/userinfobot)
2. Send any message
3. Copy the ID and add it to `ALLOWED_USER_IDS`

### Claude CLI OAuth Token

The bot requires the Claude CLI OAuth token for authentication. You can get it by running:

```bash
claude setup-token
```

passing the obtained token as an environment variable `CLAUDE_CLI_OAUTH_TOKEN` when running the bot.

### Telegram Bot Token
Create a new bot using [BotFather](https://t.me/BotFather) and obtain the Telegram Bot Token.

### Github Repository Access

To enable git operations and access to your repositories: 
You can create a deploy key in your GitHub repository and mount the corresponding private SSH key into the container. Then, set the `GIT_SSH_COMMAND` environment variable to use that key for git operations. For example:
```
GIT_SSH_COMMAND="ssh -i /home/appuser/.ssh/git"
```

You also need to set the git author and committer information using the following environment variables:

```
GIT_AUTHOR_NAME=claudebot
GIT_AUTHOR_EMAIL=xxx
GIT_COMMITTER_NAME=claudebot
GIT_COMMITTER_EMAIL=xxx
```

## Telegram Commands

### Project Management

- `/start` - Welcome message and bot introduction
- `/select` - Select or list available projects
- `/current` - Show currently selected project and branch

### Claude Interaction

- **Regular message** - Send message to Claude (resumes session)
- **`!message`** - Start fresh Claude session (doesn't resume)
- **`?message`** - Use plan mode (analyze without executing)
- `/kill` - Terminate the current Claude session
- `/checklogin` - Verify Claude CLI authentication status

### Git Operations

- `/gstat` - Show git status
- `/gdiff` - Show git diff
- `/gco` - Checkout a branch
- `/gpush` - Commit and push to branch
- `/gfetch` - Fetch updates from remote
- `/greset` - Hard reset and pull latest changes
- `/gclone <repo_url>` - Clone a new repository

## 📝 License

MIT License. See [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- [Claude AI](https://claude.ai)
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)

---

**Note**: This bot is an unofficial integration and is not affiliated with or endorsed by Anthropic or Claude AI.
