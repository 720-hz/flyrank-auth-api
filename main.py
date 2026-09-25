from fastapi import FastAPI

from config import supabase, PORT  # creating the client also validates .env

app = FastAPI(title="FlyRank Auth API", version="0.1.0")

if __name__ == "__main__":
    import uvicorn

    print("Server running and connected to Supabase")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
