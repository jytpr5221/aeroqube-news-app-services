#!/usr/bin/env python
"""
API Examples for The Hindu News Summarizer

This script demonstrates how to use the API endpoints with example requests.
Make sure the API server is running before executing these examples.
"""

import requests
import json
import time
from pprint import pprint

# API base URL - change this if your server runs on a different host/port
API_BASE_URL = "http://localhost:5000"

def print_response(response):
    """Pretty print the API response"""
    print(f"Status Code: {response.status_code}")
    try:
        json_response = response.json()
        print("Response:")
        pprint(json_response)
    except ValueError:
        print("Response (not JSON):", response.text)
    print("-" * 50)

def check_status():
    """Check the API status"""
    print("\n=== Checking API Status ===")
    response = requests.get(f"{API_BASE_URL}/status")
    print_response(response)

def extract_news(languages=None, background=True):
    """Start the news extraction process"""
    print("\n=== Extracting News ===")
    
    # Build query parameters
    params = {}
    if languages:
        params['languages'] = languages
    params['background'] = str(background).lower()
    
    # Make the request
    response = requests.post(f"{API_BASE_URL}/extract", params=params)
    print_response(response)
    
    return response.json()

def get_news(language=None, limit=None, offset=0):
    """Get news articles"""
    print(f"\n=== Getting News Articles {f'in {language}' if language else ''} ===")
    
    # Build query parameters
    params = {}
    if language:
        params['language'] = language
    if limit:
        params['limit'] = limit
    if offset:
        params['offset'] = offset
    
    # Make the request
    response = requests.get(f"{API_BASE_URL}/news", params=params)
    print_response(response)
    
    return response.json()

def wait_for_processing(max_wait_time=600):
    """Wait for the extraction process to complete"""
    print("\n=== Waiting for extraction to complete ===")
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        # Check the status
        response = requests.get(f"{API_BASE_URL}/status")
        status_data = response.json()
        
        # If not processing anymore, we're done
        if not status_data.get('processing', False):
            print(f"Processing completed in {time.time() - start_time:.1f} seconds")
            return True
        
        # Still processing, wait and check again
        print(f"Still processing... (elapsed: {time.time() - start_time:.1f}s)")
        time.sleep(10)
    
    print(f"Timed out after waiting {max_wait_time} seconds")
    return False

def save_articles_to_file(articles, filename="downloaded_articles.json"):
    """Save articles to a JSON file"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(articles)} articles to {filename}")

def run_demo():
    """Run the complete API demo"""
    # Check the initial status
    check_status()
    
    # Extract news articles in Hindi and Tamil
    extract_news(languages="hi,ta")
    
    # Wait for processing to complete (up to 10 minutes)
    if wait_for_processing(600):
        # Get all articles
        all_articles = get_news()
        
        # Get Hindi articles only, limited to 3
        hindi_articles = get_news(language="hi", limit=3)
        
        if 'articles' in hindi_articles and hindi_articles['articles']:
            # Save Hindi articles to file
            save_articles_to_file(
                hindi_articles['articles'], 
                filename="hindi_articles.json"
            )

if __name__ == "__main__":
    run_demo() 