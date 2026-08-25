"""
Script to configure PostgreSQL database by executing SQL scripts.

This script reads SQL files from the sql/ directory and executes them in order
to set up database extensions, tables, and other structures.
"""

import logging
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PostgreSQLConfigurator:
    """
    PostgreSQL database configurator that executes SQL scripts.
    """
    
    def __init__(self, connection_params: dict):
        """
        Initialize the configurator with database connection parameters.
        
        Args:
            connection_params: Dictionary with database connection parameters
        """
        self.connection_params = connection_params
        self.connection = None
    
    def connect(self) -> None:
        """
        Establish connection to PostgreSQL database.
        
        Raises:
            psycopg2.Error: If connection fails
        """
        try:
            logger.info("Connecting to PostgreSQL database...")
            self.connection = psycopg2.connect(**self.connection_params)
            self.connection.autocommit = True
            logger.info("Successfully connected to PostgreSQL")
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise
    
    def disconnect(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            logger.info("Disconnected from PostgreSQL")
    
    def execute_sql_file(self, file_path: Path) -> bool:
        """
        Execute SQL commands from a file.
        
        Args:
            file_path: Path to the SQL file
            
        Returns:
            True if execution was successful, False otherwise
        """
        if not file_path.exists():
            logger.error(f"SQL file not found: {file_path}")
            return False
        
        try:
            logger.info(f"Executing SQL file: {file_path.name}")
            
            with open(file_path, 'r', encoding='utf-8') as file:
                sql_content = file.read()
            
            # Skip empty files
            if not sql_content.strip():
                logger.warning(f"SQL file is empty: {file_path.name}")
                return True
            
            cursor = self.connection.cursor()
            
            # Execute the SQL content
            cursor.execute(sql_content)
            
            # Fetch results if any (for queries like SELECT)
            if cursor.description:
                results = cursor.fetchall()
                if results:
                    logger.info(f"Query results from {file_path.name}:")
                    for row in results:
                        logger.info(f"  {row}")
            
            cursor.close()
            logger.info(f"Successfully executed: {file_path.name}")
            return True
            
        except psycopg2.Error as e:
            logger.error(f"Error executing {file_path.name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error executing {file_path.name}: {e}")
            return False
    
    def execute_sql_scripts(self, sql_dir: Path, pattern: str = "*.sql") -> bool:
        """
        Execute all SQL scripts in a directory in alphabetical order.
        
        Args:
            sql_dir: Directory containing SQL scripts
            pattern: File pattern to match (default: "*.sql")
            
        Returns:
            True if all scripts executed successfully, False otherwise
        """
        if not sql_dir.exists():
            logger.error(f"SQL directory not found: {sql_dir}")
            return False
        
        # Get all SQL files and sort them
        sql_files = sorted(sql_dir.glob(pattern))
        
        if not sql_files:
            logger.warning(f"No SQL files found in {sql_dir} matching pattern {pattern}")
            return True
        
        logger.info(f"Found {len(sql_files)} SQL files to execute")
        
        success_count = 0
        for sql_file in sql_files:
            if self.execute_sql_file(sql_file):
                success_count += 1
            else:
                logger.error(f"Failed to execute {sql_file.name}, stopping execution")
                return False
        
        logger.info(f"Successfully executed {success_count}/{len(sql_files)} SQL files")
        return True


def load_connection_params() -> dict:
    """
    Load PostgreSQL connection parameters from environment variables.
    
    Returns:
        Dictionary with connection parameters
        
    Raises:
        ValueError: If required environment variables are missing
    """
    # Load environment variables
    load_dotenv()
    
    # Default connection parameters (matching docker-compose.yml)
    connection_params = {
        'host': os.getenv('PGHOST', 'localhost'),
        'port': int(os.getenv('PGPORT', 5432)),
        'database': os.getenv('PGDATABASE', 'aidb'),
        'user': os.getenv('PGUSER', 'admin'),
        'password': os.getenv('PGPASSWORD', 'Admin12345678')
    }
    
    # Validate required parameters
    required_params = ['host', 'port', 'database', 'user', 'password']
    missing_params = [param for param in required_params if not connection_params.get(param)]
    
    if missing_params:
        raise ValueError(f"Missing required connection parameters: {missing_params}")
    
    return connection_params


def main():
    """Main function to configure PostgreSQL database."""
    try:
        logger.info("Starting PostgreSQL configuration")
        
        # Load connection parameters
        connection_params = load_connection_params()
        logger.info(f"Connecting to PostgreSQL at {connection_params['host']}:{connection_params['port']}")
        
        # Initialize configurator
        configurator = PostgreSQLConfigurator(connection_params)
        
        # Connect to database
        configurator.connect()
        
        try:
            # Get script directory
            script_dir = Path(__file__).parent
            sql_base_dir = script_dir / 'sql'
            
            # Execute extensions first
            extensions_dir = sql_base_dir / 'extensions'
            if extensions_dir.exists():
                logger.info("Installing database extensions...")
                if not configurator.execute_sql_scripts(extensions_dir):
                    logger.error("Failed to install extensions")
                    return False
            
            # Execute other SQL scripts in order
            for subdir in ['tables', 'indexes', 'functions', 'triggers', 'data']:
                sql_dir = sql_base_dir / subdir
                if sql_dir.exists():
                    logger.info(f"Executing {subdir} scripts...")
                    if not configurator.execute_sql_scripts(sql_dir):
                        logger.error(f"Failed to execute {subdir} scripts")
                        return False
            
            logger.info("PostgreSQL configuration completed successfully")
            return True
            
        finally:
            # Always disconnect
            configurator.disconnect()
    
    except Exception as e:
        logger.error(f"Error in PostgreSQL configuration: {e}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
