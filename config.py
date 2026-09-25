"""
Loads environment variables and creates a single shared Supabase client.
Every other module imports `supabase` from here instead of creating its
own client — one connection, one source of truth, same pattern as db.py
in the previous assignment.
"""
import os
import sys

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
PORT = int(os.environ.get("PORT", 8000))

if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit(
        "Missing SUPABASE_URL or SUPABASE_KEY. Copy .env.example to .env "
        "and fill in your project's values from Supabase Dashboard -> "
        "Project Settings -> API."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
