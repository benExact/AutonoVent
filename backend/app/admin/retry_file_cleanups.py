"""Retry removing files left behind by permanent product deletes. Run from backend: python -m app.admin.retry_file_cleanups"""

import logging
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.file_cleanup import FileCleanup
from app.products.deletion import run_file_cleanups, storage_roots


def main() -> int:
    if len(sys.argv) > 1:
        print("This command does not accept arguments.", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    roots = storage_roots(get_settings())
    with Session(get_engine(), expire_on_commit=False) as session:
        queued = session.scalar(select(func.count()).select_from(FileCleanup)) or 0
        pending = run_file_cleanups(session, roots)
    print(f"Queued files checked: {queued}. Still pending: {len(pending)}.")
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
