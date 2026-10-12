from .core import BotError, Config


def main():
    try:
        config = Config.from_env()
        from .bot import MontageClient
    except BotError as exc:
        raise SystemExit(str(exc)) from None
    except ImportError:
        raise SystemExit("Install optional bot dependencies: pip install -r discord_bot/requirements.txt") from None
    MontageClient(config).run(config.token)


if __name__ == "__main__":
    main()
