from fastapi import FastAPI, Query, HTTPException
from httpx import AsyncClient, HTTPStatusError, RequestError
from pydantic import BaseModel
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import AsyncOpenAI
import os
import asyncio
import uvicorn
import logging
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global async_client
    async_client = AsyncClient()  # Start HTTP client
    yield
    await async_client.aclose()  # Close HTTP client

app = FastAPI(lifespan=lifespan)

logger = logging.getLogger("fastapi_app")
load_dotenv()
client = AsyncOpenAI()

# API keys for search engines
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CX = os.getenv("GOOGLE_CX")
BING_API_KEY = os.getenv("BING_API_KEY")

# client = OpenAI(
#   api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
# )

async def scrape_multiple_urls(urls):
    tasks = [scrape_url(url) for url in urls]  # Collect coroutines
    results = await asyncio.gather(*tasks)  # Execute them concurrently
    return [result["content"] for result in results]  # Extract content

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
async def scrape_url(url: str):
    """
    Scrape a URL and extract the main content.
    """
    try:
        response = await async_client.get(url, timeout=10) 
        response.raise_for_status()  # Raises an error for HTTP 4xx and 5xx responses
        
        soup = BeautifulSoup(response.text, 'html.parser')  # Use response.text (not .content)
        p_list = soup.find_all('p')

        # Filter paragraphs with sufficient content
        filtered_p_list = [p.get_text(strip=True) for p in p_list if len(p.get_text(strip=True)) > 100]
        extracted_content = "\n".join(filtered_p_list)

        if not extracted_content:
            raise HTTPException(status_code=400, detail="No readable content found on the page.")

        return {"url": url, "content": extracted_content}
    except HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"HTTP error: {e}")
    except RequestError as e:
        raise HTTPException(status_code=500, detail=f"Request failed: {e}")


@app.post("/summarize")
async def summarize(request: SummarizeRequest):
    """
    Summarize the given content using OpenAI API.
    """
    content = request.content
    
    if not content:
        raise HTTPException(status_code=400, detail="Please provide content to summarize.")

    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful summarization assistant."},
                {"role": "user", "content": f"Summarize this content in 200 words:\n{content}"}
            ],
            temperature=0
        )
        summary = response.choices[0].message.content if response.choices else "No summary available."
        return {"summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    
@app.get("/search_scrape_summarize")
async def search_scrape_summarize(topic: str, engine: str = "google"):
    """
    Perform a search, scrape the top 3 websites, and return a unified summary.
    """
    try:
        # Step 1: Search for the topic
        articles_response = await search_topic(topic, engine)

        # Extract the "articles" list from the response
        articles = articles_response["articles"]

        # Get the top 3 URLs from the articles
        urls = [article["link"] for article in articles[:3]]
        # logger.debug("URLs extracted")

        # Step 2: Scrape content from each URL
        contents = await scrape_multiple_urls(urls)
        all_content = "\n".join(contents)   
        # logger.debug("Content from all 3 websites extracted")

        # # Step 3: Split content into manageable chunks
        max_chunk_size = 3000  # Adjust as needed to stay within limits
        chunks = [all_content[i:i + max_chunk_size] for i in range(0, len(all_content), max_chunk_size)]
        # logger.debug(f"Got all separate chunks: {len(chunks)}")

        # Step 4: Summarize each chunk separately
        tasks = [summarize(SummarizeRequest(content=chunk)) for chunk in chunks]
        summaries = await asyncio.gather(*tasks)
        chunk_summaries = [summary["summary"] for summary in summaries]
        # logger.debug(f"Got summaries for each chunk: {len(chunk_summaries)}")

        # Step 5: Summarize the combined summaries
        final_summary_request = SummarizeRequest(content=" ".join(chunk_summaries))
        final_summary = await summarize(final_summary_request)
        # return {"topic": topic, "summary": final_summary, "sources": urls}
        return final_summary

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
