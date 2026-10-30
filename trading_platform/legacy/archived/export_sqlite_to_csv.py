import sqlite3
import pandas as pd
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('CSVExporter')

DB_PATH = "data/ml/historical_candles.sqlite"
CSV_PATH = "data/ml/candles_export.csv"

def export_to_csv():
    """Exports the SQLite database to a flat CSV file for Colab/Kaggle."""
    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found at {DB_PATH}. Run harvest_data.py first.")
        return

    logger.info(f"Connecting to database at {DB_PATH}...")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # Load all candles, ordered chronologically
        query = "SELECT * FROM candles ORDER BY asset, timeframe, timestamp ASC"
        df = pd.read_sql_query(query, conn)
        
        conn.close()
        
        if df.empty:
            logger.warning("Database is empty. Nothing to export.")
            return
            
        logger.info(f"Successfully loaded {len(df)} rows from database.")
        
        # Ensure target directory exists
        os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
        
        # Save to CSV
        logger.info(f"Writing data to {CSV_PATH}...")
        df.to_csv(CSV_PATH, index=False)
        
        logger.info(f"✅ Export complete! File size: {os.path.getsize(CSV_PATH) / (1024*1024):.2f} MB")
        logger.info(f"You can now upload {CSV_PATH} to Google Colab or Kaggle.")
        
    except Exception as e:
        logger.error(f"Error during export: {e}")

if __name__ == "__main__":
    export_to_csv()
