"""Offline operations: validate questions, migrate, back up and export."""
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import os

from waiterbot.app import export_results
from waiterbot.catalog import Catalog, ROLES
from waiterbot.storage import Store

BASE_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "migrate", "backup", "export"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    load_dotenv(BASE_DIR / ".env")
    path = Path(os.getenv("BOT_DB_PATH", "data/bot.sqlite3"))
    store = Store(path if path.is_absolute() else BASE_DIR / path)
    if args.command == "check":
        for role, count in Catalog(BASE_DIR).reload().items():
            print(f"{ROLES[role]['label']}: {count} вопросов")
        print("Проверка структуры вопросов пройдена. Telegram не вызывается.")
    elif args.command == "migrate":
        if store.db_path.exists():
            store.backup(BASE_DIR / "backups" / f"before-migration-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")
        store.initialize()
        print(store.migrate_legacy(BASE_DIR, ROLES))
    else:
        if not store.db_path.is_file():
            raise SystemExit("База не создана: сначала выполните migrate или запустите bot.py.")
        if args.command == "backup":
            output = args.output or BASE_DIR / "backups" / f"waiter-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
            if output.exists():
                raise SystemExit("Файл назначения уже существует; выберите новый.")
            store.backup(output)
        else:
            output = args.output or BASE_DIR / "data" / f"results-{datetime.now():%Y%m%d-%H%M%S-%f}.xlsx"
            if output.exists():
                raise SystemExit("Файл назначения уже существует; выберите новый.")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(export_results(store.read_results()))
        print(output)


if __name__ == "__main__":
    main()
