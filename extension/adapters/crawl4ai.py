import asyncio
from crawl4ai import AsyncWebCrawler

async def main():
    print("Starting the crawler...")
    
    # Initialize the asynchronous web crawler
    async with AsyncWebCrawler(verbose=True) as crawler:
        # Run the crawler on a target URL
        result = await crawler.arun(url="https://news.ycombinator.com/")
        
        if result.success:
            # Print a snippet of the extracted Markdown content
            print("\n--- Crawl Result (First 500 characters) ---")
            print(result.markdown[:500])
            print("...\n")
            
            # Print metadata about the crawl
            print(f"Total markdown length: {len(result.markdown)} characters")
            print(f"Extracted internal links: {len(result.links.get('internal', []))}")
        else:
            print(f"Failed to crawl the page. Error: {result.error_message}")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())