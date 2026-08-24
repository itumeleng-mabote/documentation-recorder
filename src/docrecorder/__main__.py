def main() -> None:
    try:
        from docrecorder.app import main as app_main
    except ModuleNotFoundError as exc:
        missing = str(exc)
        if "tkinter" in missing or "_tkinter" in missing:
            raise SystemExit(
                "Tkinter is not available in this Python.\n"
                "On macOS Homebrew, install the matching python-tk package "
                "(for example: brew install python-tk@3.14) or use the installer from python.org."
            ) from exc
        raise
    app_main()


if __name__ == "__main__":
    main()
