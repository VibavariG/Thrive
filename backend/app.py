from fastapi import FastAPI, Query, HTTPException
from httpx import AsyncClient
from pydantic import BaseModel
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import AsyncOpenAI
import os
import requests

load_dotenv()

app = FastAPI()

# Initialize HTTP client
async_client = AsyncClient()

# API keys for search engines
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CX = os.getenv("GOOGLE_CX")
BING_API_KEY = os.getenv("BING_API_KEY")

client = AsyncOpenAI()

# client = OpenAI(
#   api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
# )

class SummarizeRequest(BaseModel):
    content: str

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
async def scrape_and_summarize(url: str):
    """
    Scrape a URL, extract the main content, and summarize it using OpenAI API.
    """
    try:
        # Scrape the content from the URL
        response = requests.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        p_list = soup.find_all('p')
        
        # Filter paragraphs with sufficient content
        filtered_p_list = [p.get_text() for p in p_list if len(p.get_text()) > 100]
        content = "\n".join(filtered_p_list)

        if not content:
            raise HTTPException(status_code=400, detail="No sufficient content found to summarize.")

        # Summarize the content using OpenAI API
        try:
            summary_response = await client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful summarization assistant."},
                    {"role": "user", "content": f"Summarize this content in 200 words:\n{content}"}
                ]
            )
            summary = summary_response.choices[0].message.content
            return {"url": url, "summary": summary}

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Summarization failed: {str(e)}")

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Request failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")
    
if __name__ == "__main__":
    app.run(debug=True)
