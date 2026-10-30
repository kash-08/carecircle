"""Create the database tables.

    python -m app.init_db            create any missing tables (safe to re-run)
    python -m app.init_db --reset    DROP everything, then recreate (development only!)

create_all never alters tables that already exist. While models are still changing,
use --reset. Once real data matters, switch to migrations (Alembic).
"""
import sys

from .database import engine
from .models import Base


def main() -> None:
    if "--reset" in sys.argv:
        answer = input(f"This DELETES ALL DATA in {engine.url.render_as_string(hide_password=True)}. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Cancelled.")
            return
        Base.metadata.drop_all(engine)
        print("Dropped all tables.")
    Base.metadata.create_all(engine)
    print(f"Tables ready: {', '.join(sorted(Base.metadata.tables))}")


if __name__ == "__main__":
    main()