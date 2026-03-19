"""
API key loader — tries .env first, then macOS keychain.

Usage:
    from shared.api_keys import get_anthropic_key, get_openai_key
"""
import os
import subprocess


def _keychain(name):
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", name, "-w"],
            capture_output=True, text=True, timeout=5
        )
        val = result.stdout.strip()
        return val if val else None
    except Exception:
        return None


def _dotenv():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_dotenv()


def get_anthropic_key():
    return (os.environ.get("ANTHROPIC_API_KEY")
            or _keychain("anthropic-api-key")
            or _keychain("ANTHROPIC_API_KEY"))


def get_openai_key():
    return (os.environ.get("OPENAI_API_KEY")
            or _keychain("openai-api-key")
            or _keychain("OPENAI_API_KEY"))
