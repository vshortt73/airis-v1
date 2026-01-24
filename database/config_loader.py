"""
Database Configuration Loader

Loads runtime configuration from PostgreSQL instead of config.py files.
Provides hot-reload capability and persistent storage.

Architecture:
- Bootstrap config (DB connection, critical paths) stays in config.py
- Runtime config (tokens, thresholds, features) loads from database
- Cache in memory for fast access
- Hot reload without server restart
"""

import os
import sys
from typing import Any, Dict, Optional
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras


class DatabaseConfig:
    """Configuration loader from PostgreSQL"""

    def __init__(self):
        self._config_cache: Dict[str, Any] = {}
        self._last_load: Optional[datetime] = None
        self._load_attempted = False

    def get_db_connection(self):
        """Get database connection using bootstrap config"""
        from app import config as bootstrap_config

        password = os.environ.get('IRIS_DB_PASSWORD') or getattr(bootstrap_config, 'DB_PASSWORD', None)
        conn_params = {
            'host': bootstrap_config.DB_HOST,
            'port': bootstrap_config.DB_PORT,
            'database': bootstrap_config.DB_NAME,
            'user': bootstrap_config.DB_USER
        }
        if password:
            conn_params['password'] = password
        return psycopg2.connect(**conn_params)

    def load_from_database(self, force_reload: bool = False) -> bool:
        """
        Load configuration from database into memory cache

        Args:
            force_reload: Force reload even if recently loaded

        Returns:
            True if successful, False if error
        """
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cursor.execute("""
                SELECT key, value, value_type, default_value
                FROM system_config
                ORDER BY category, key
            """)

            rows = cursor.fetchall()

            # Parse values based on type
            for row in rows:
                key = row['key']
                value_str = row['value']
                value_type = row['value_type']

                # Type conversion
                if value_type == 'int':
                    value = int(value_str)
                elif value_type == 'float':
                    value = float(value_str)
                elif value_type == 'bool':
                    value = value_str.lower() in ('true', '1', 'yes')
                elif value_type == 'json':
                    import json
                    value = json.loads(value_str)
                else:  # string
                    value = value_str

                self._config_cache[key] = value

            cursor.close()
            conn.close()

            self._last_load = datetime.now()
            self._load_attempted = True

            print(f"[config_loader] ✓ Loaded {len(self._config_cache)} config values from database")
            return True

        except Exception as e:
            print(f"[config_loader] ✗ Failed to load from database: {e}")
            self._load_attempted = True
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value

        Args:
            key: Configuration key
            default: Default value if not found

        Returns:
            Configuration value
        """
        # Load from database on first access
        if not self._load_attempted:
            self.load_from_database()

        return self._config_cache.get(key, default)

    def set(self, key: str, value: Any, modified_by: str = 'system') -> bool:
        """
        Update configuration value (both cache and database)

        Args:
            key: Configuration key
            value: New value
            modified_by: Who made the change

        Returns:
            True if successful
        """
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Convert value to string for storage
            if isinstance(value, bool):
                value_str = 'true' if value else 'false'
            else:
                value_str = str(value)

            # Update database
            cursor.execute("""
                UPDATE system_config
                SET value = %s,
                    last_modified = NOW(),
                    modified_by = %s
                WHERE key = %s
            """, (value_str, modified_by, key))

            if cursor.rowcount == 0:
                print(f"[config_loader] ✗ Key not found: {key}")
                cursor.close()
                conn.close()
                return False

            conn.commit()
            cursor.close()
            conn.close()

            # Update cache
            self._config_cache[key] = value

            print(f"[config_loader] ✓ Updated {key} = {value} (by {modified_by})")
            return True

        except Exception as e:
            print(f"[config_loader] ✗ Failed to update {key}: {e}")
            return False

    def create_or_update(self, key: str, value: Any, category: str = 'general',
                         value_type: str = 'string', description: str = '',
                         modified_by: str = 'system') -> bool:
        """
        Create or update a configuration value (upsert)

        Args:
            key: Configuration key
            value: Value to store
            category: Config category (e.g., 'video', 'face_monitoring')
            value_type: Type hint ('string', 'int', 'float', 'bool', 'json')
            description: Human-readable description
            modified_by: Who made the change

        Returns:
            True if successful
        """
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Convert value to string for storage
            if isinstance(value, bool):
                value_str = 'true' if value else 'false'
            elif value_type == 'json':
                import json
                value_str = json.dumps(value) if not isinstance(value, str) else value
            else:
                value_str = str(value)

            # Upsert using ON CONFLICT
            cursor.execute("""
                INSERT INTO system_config (category, key, value, value_type, default_value, description, modified_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    last_modified = NOW(),
                    modified_by = EXCLUDED.modified_by
            """, (category, key, value_str, value_type, value_str, description, modified_by))

            conn.commit()
            cursor.close()
            conn.close()

            # Update cache
            self._config_cache[key] = value

            print(f"[config_loader] ✓ Upserted {key} = {value} (by {modified_by})")
            return True

        except Exception as e:
            print(f"[config_loader] ✗ Failed to upsert {key}: {e}")
            return False

    def get_all_by_category(self, category: str) -> Dict[str, Any]:
        """Get all config values in a category"""
        if not self._load_attempted:
            self.load_from_database()

        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cursor.execute("""
                SELECT key, value, value_type, description, requires_restart
                FROM system_config
                WHERE category = %s
                ORDER BY key
            """, (category,))

            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            result = {}
            for row in rows:
                key = row['key']
                if key in self._config_cache:
                    result[key] = {
                        'value': self._config_cache[key],
                        'description': row['description'],
                        'requires_restart': row['requires_restart']
                    }

            return result

        except Exception as e:
            print(f"[config_loader] ✗ Failed to get category {category}: {e}")
            return {}

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values"""
        if not self._load_attempted:
            self.load_from_database()

        return self._config_cache.copy()

    def reload(self) -> bool:
        """Force reload from database"""
        return self.load_from_database(force_reload=True)


# Global instance
_db_config = DatabaseConfig()


def get_config(key: str, default: Any = None) -> Any:
    """
    Get configuration value from database

    This is the primary interface for accessing config values.
    Falls back to default if key not found.

    Args:
        key: Configuration key (e.g., 'FACE_GREETING_COOLDOWN_MINUTES')
        default: Default value if not found

    Returns:
        Configuration value
    """
    return _db_config.get(key, default)


def set_config(key: str, value: Any, modified_by: str = 'system') -> bool:
    """
    Update configuration value

    Args:
        key: Configuration key
        value: New value
        modified_by: Who made the change

    Returns:
        True if successful
    """
    return _db_config.set(key, value, modified_by)


def create_or_update_config(key: str, value: Any, category: str = 'general',
                            value_type: str = 'string', description: str = '',
                            modified_by: str = 'system') -> bool:
    """
    Create or update a configuration value (upsert)

    Args:
        key: Configuration key
        value: Value to store
        category: Config category (e.g., 'video', 'face_monitoring')
        value_type: Type hint ('string', 'int', 'float', 'bool', 'json')
        description: Human-readable description
        modified_by: Who made the change

    Returns:
        True if successful
    """
    return _db_config.create_or_update(key, value, category, value_type, description, modified_by)


def reload_config() -> bool:
    """Force reload configuration from database"""
    return _db_config.reload()


def get_all_config() -> Dict[str, Any]:
    """Get all configuration values"""
    return _db_config.get_all()


def get_config_by_category(category: str) -> Dict[str, Any]:
    """Get all config values in a category"""
    return _db_config.get_all_by_category(category)


# Convenience function for backward compatibility with old config.py access
def inject_into_module(module):
    """
    Inject database config values into a module (like app.config)

    This allows existing code using config.FACE_GREETING_COOLDOWN_MINUTES
    to seamlessly work with database-backed config.

    Usage:
        from database.config_loader import inject_into_module
        inject_into_module(config)
    """
    all_config = get_all_config()
    for key, value in all_config.items():
        setattr(module, key, value)

    print(f"[config_loader] ✓ Injected {len(all_config)} config values into {module.__name__}")

    # Debug: explicitly log SERVER_SIDE_TTS_ROUTING
    if 'SERVER_SIDE_TTS_ROUTING' in all_config:
        print(f"[config_loader] ✓ SERVER_SIDE_TTS_ROUTING = {all_config['SERVER_SIDE_TTS_ROUTING']} (from database)")
    else:
        print(f"[config_loader] ⚠ SERVER_SIDE_TTS_ROUTING not found in database - using fallback")
