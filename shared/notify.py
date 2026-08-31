import os, smtplib, time, requests
from email.mime.text import MIMEText
from datetime import datetime
from zoneinfo import ZoneInfo

def send_email(subject: str, body: str, cfg):
    if not cfg.smtp_user or not cfg.email_to:
        return
    to_addrs = [a.strip() for a in cfg.email_to.split(",") if a.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"{cfg.email_subject_prefix} {subject}"
    msg["From"] = cfg.email_from
    msg["To"] = ", ".join(to_addrs)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as s:
            if cfg.smtp_starttls:
                s.starttls()
            s.login(cfg.smtp_user, cfg.smtp_password)
            s.sendmail(cfg.email_from, to_addrs, msg.as_string())
    except Exception as e:
        print(f"❌ Email send failed: {e}")


def send_telegram(text: str, cfg):
    if not cfg.bot_token or not cfg.chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        requests.post(url, data={"chat_id": cfg.chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")


def send_telegram_chunked(text: str, cfg, max_len: int = 4000):
    if not text:
        return
    if len(text) <= max_len:
        send_telegram(text, cfg)
        return
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > max_len:
            send_telegram(chunk, cfg)
            chunk = line
        else:
            chunk += line + "\n"
    if chunk:
        send_telegram(chunk, cfg)


def build_schedule_text(schedule_hours: list[int], tz_name: str = "Asia/Seoul"):
    now = datetime.now(ZoneInfo(tz_name))
    lines = []
    current_seq = 0
    for idx, h in enumerate(schedule_hours, 1):
        label = f"{idx}회: {h:02d}:00"
        if now.hour == h:
            label += " (현재)"
            current_seq = idx
        lines.append(label)
    return "\n".join(lines), current_seq
