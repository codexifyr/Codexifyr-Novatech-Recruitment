from pathlib import Path

import uvicorn
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

# Root project ki .env file load karega
load_dotenv(ROOT_DIR / ".env", override=True)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )