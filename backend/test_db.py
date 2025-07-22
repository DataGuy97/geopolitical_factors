from app.database import engine, mongo_client, mongo_db
from sqlalchemy import text
import sys


def test_postgresql():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print("✅ PostgreSQL connected successfully!")
            print(f"   Version: {version[:50]}...")
            return True
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        return False


def test_mongodb():
    try:
        # Test connection
        mongo_client.admin.command('ping')

        # Test database access
        collections = mongo_db.list_collection_names()
        print("✅ MongoDB connected successfully!")
        print(f"   Database: {mongo_db.name}")
        print(f"   Collections: {collections if collections else 'No collections yet'}")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False


if __name__ == "__main__":
    print("Testing database connections...\n")

    pg_success = test_postgresql()
    mongo_success = test_mongodb()

    print(f"\n{'=' * 50}")
    if pg_success and mongo_success:
        print("🎉 All database connections successful!")
        sys.exit(0)
    else:
        print("⚠️  Some connections failed. Check your .env file.")
        sys.exit(1)