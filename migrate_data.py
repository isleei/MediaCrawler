import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

# Load environment variables
load_dotenv()

from api.services.weibo_storage import weibo_storage
from sqlalchemy import create_engine, text
from config.db_config import mysql_db_config

def manual_init_db():
    # Force type conversion
    host = os.getenv("MYSQL_DB_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_DB_PORT", "3306"))
    user = os.getenv("MYSQL_DB_USER", "root")
    password = os.getenv("MYSQL_DB_PWD", "")
    dbname = os.getenv("MYSQL_DB_NAME", "yuqing")
    
    print(f"Checking database {dbname} on {host}:{port}...")
    from database.db_utils import create_mysql_engine_safe
    from database.models import Base
    
    # First, ensure database exists
    engine_no_db = create_mysql_engine_safe(
        host=host, port=port, user=user, password=password, database='mysql'
    )
    with engine_no_db.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {dbname}"))
    
    # Then, create tables
    engine = create_mysql_engine_safe(
        host=host, port=port, user=user, password=password, database=dbname
    )
    print("Creating tables if not exist...")
    Base.metadata.create_all(engine)

if __name__ == "__main__":
    try:
        manual_init_db()
        print("Starting migration from Redis to MySQL...")
        weibo_storage.migrate_from_redis()
        print("Migration process finished successfully!")
    except Exception as e:
        print(f"Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
