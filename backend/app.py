from fastapi import FastAPI, Query
from httpx import AsyncClient
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os
import requests
import random

load_dotenv()

app = FastAPI()

# Initialize HTTP client
async_client = AsyncClient()

# API keys for search engines
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CX = os.getenv("GOOGLE_CX")
BING_API_KEY = os.getenv("BING_API_KEY")

@app.get("/search")
async def search_topic(
    topic: str = Query(..., description="Topic to search for"),
    engine: str = Query("google", description="Search engine to use ('google' or 'bing')")
):
    """
    Fetch top articles for a given topic using Google or Bing.
    """
    try:
        if engine == "google":
            url = (
                f"https://www.googleapis.com/customsearch/v1"
                f"?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={topic}"
            )
        elif engine == "bing":
            url = (
                f"https://api.bing.microsoft.com/v7.0/search"
                f"?q={topic}"
            )
        else:
            return {"error": "Unsupported search engine. Use 'google' or 'bing'."}

        # Send the request
        headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY} if engine == "bing" else {}
        response = await async_client.get(url, headers=headers)
        response.raise_for_status()

        # Process results
        results = response.json()
        articles = []
        if engine == "google":
            for item in results.get("items", []):
                articles.append({"title": item["title"], "link": item["link"]})
        elif engine == "bing":
            for item in results.get("webPages", {}).get("value", []):
                articles.append({"title": item["name"], "link": item["url"]})

        return {"query": topic, "engine": engine, "articles": articles}

    except Exception as e:
        return {"error": str(e)}

@app.get("/scrape")
async def scrape_url(url: str):
    """
    Scrape a URL for its content.
    """
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/89.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.64',
        # Add more user agents as needed
    ]

    headers = {
        'User-Agent': random.choice(user_agents)
    }
    try:
        # Fetch page content
        response = requests.get(url, headers=headers)
        print(response)
        # response = await async_client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # Extract visible text
        text = soup.get_text(strip=True)
        return {"url": url, "content": text[:1000]}  # Return first 1000 characters for brevity

    except Exception as e:
        return {"error": str(e)}

# Graceful shutdown
@app.on_event("shutdown")
async def shutdown_event():
    await async_client.aclose()
