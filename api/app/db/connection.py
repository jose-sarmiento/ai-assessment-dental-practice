import os
from urllib.parse import quote_plus

import psycopg2
from pgvector.psycopg2 import register_vector


def get_conn():
    url = (
        f"postgresql://{quote_plus(os.getenv('DB_USER'))}:{quote_plus(os.getenv('DB_PASSWORD'))}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    conn = psycopg2.connect(url)
    register_vector(conn)
    return conn
