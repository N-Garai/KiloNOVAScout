from strands import Agent, tool
import requests

@tool
def send_telegram_interactive_briefing(bot_token: str, chat_id: str, summary_text: str, run_id: str) -> dict:
    """Dispatches human-in-the-loop execution card with single-click approval buttons via Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": summary_text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Approve & Fire Slew", "callback_data": f"APPROVE_{run_id}"},
                    {"text": "Abort Execution", "callback_data": f"ABORT_{run_id}"}
                ]
            ]
        }
    }
    resp = requests.post(url, json=payload, timeout=5)
    return {"status_code": resp.status_code, "delivered": resp.status_code == 200}

notification_agent = Agent(
    name="NotificationDispatcherAgent",
    system_prompt="You are an autonomous operations dispatcher coordinating human approval workflows.",
    tools=[send_telegram_interactive_briefing]
)