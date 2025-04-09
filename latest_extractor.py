import asyncio
import json
import os
import re
import glob
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse, urljoin
from crawl4ai import AsyncWebCrawler, BrowserConfig
import hashlib
import urllib.request
import ssl
from PIL import Image
import io
import shutil
from google.cloud import texttospeech
from google.oauth2 import service_account
from dotenv import load_dotenv
# Add Appwrite imports
from appwrite.client import Client
from appwrite.services.storage import Storage
from appwrite.input_file import InputFile
from appwrite.id import ID
from appwrite.permission import Permission
from appwrite.role import Role


# Load environment variables for API credentials
load_dotenv()

# Set up TTS credentials
credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "awesome-aspect-455006-b6-e45e9e01c19e.json")
if os.path.exists(credentials_path):
    credentials = service_account.Credentials.from_service_account_file(credentials_path)
else:
    print(f"Warning: TTS credentials file not found at {credentials_path}")
    credentials = None

# Map of Indian languages with their codes and TTS codes
# Updated to match translate.py and include all supported languages
INDIAN_LANGUAGES = {
    'as': {'name': 'Assamese', 'tts_code': 'as-IN'},
    'bn': {'name': 'Bengali', 'tts_code': 'bn-IN'},
    'bho': {'name': 'Bhojpuri', 'tts_code': 'hi-IN'},  # Fallback to Hindi
    'gu': {'name': 'Gujarati', 'tts_code': 'gu-IN'},
    'hi': {'name': 'Hindi', 'tts_code': 'hi-IN'},
    'kn': {'name': 'Kannada', 'tts_code': 'kn-IN'},
    'kok': {'name': 'Konkani', 'tts_code': 'hi-IN'},  # Fallback to Hindi
    'mai': {'name': 'Maithili', 'tts_code': 'hi-IN'},  # Fallback to Hindi
    'ml': {'name': 'Malayalam', 'tts_code': 'ml-IN'},
    'mni-Mtei': {'name': 'Manipuri', 'tts_code': 'en-IN'},  # Fallback to English
    'mr': {'name': 'Marathi', 'tts_code': 'mr-IN'},
    'or': {'name': 'Odia', 'tts_code': 'or-IN'},
    'pa': {'name': 'Punjabi', 'tts_code': 'pa-IN'},
    'sa': {'name': 'Sanskrit', 'tts_code': 'hi-IN'},  # Fallback to Hindi
    'sd': {'name': 'Sindhi', 'tts_code': 'hi-IN'},   # Fallback to Hindi
    'ta': {'name': 'Tamil', 'tts_code': 'ta-IN'},
    'te': {'name': 'Telugu', 'tts_code': 'te-IN'},
    'ur': {'name': 'Urdu', 'tts_code': 'hi-IN'},    # Fallback to Hindi
    'en': {'name': 'English_Indian', 'tts_code': 'en-IN'}
}

# Add Appwrite functions
def initialize_appwrite():
    """Initialize and return Appwrite client and storage service."""
    try:
        # Create Appwrite client
        client = Client()
        
        # Set Appwrite endpoint and project
        appwrite_endpoint = os.getenv('APPWRITE_ENDPOINT')
        appwrite_project_id = os.getenv('APPWRITE_PROJECT_ID')
        appwrite_api_key = os.getenv('APPWRITE_API_KEY')
        
        # Check if credentials are available
        if not all([appwrite_endpoint, appwrite_project_id, appwrite_api_key]):
            print("Warning: Appwrite credentials not found in environment variables")
            return None, None
        
        # Configure client
        client.set_endpoint(appwrite_endpoint)
        client.set_project(appwrite_project_id)
        client.set_key(appwrite_api_key)
        
        # Initialize storage service
        storage = Storage(client)
        
        return client, storage
    except Exception as e:
        print(f"Error initializing Appwrite: {e}")
        return None, None

def create_bucket_if_not_exists(storage, bucket_id="tts_files", bucket_name="TTS Files"):
    """Create a storage bucket if it doesn't exist."""
    if not storage:
        return False
        
    try:
        # Try to get the bucket to see if it exists
        storage.get_bucket(bucket_id)
        print(f"Bucket '{bucket_id}' already exists")
    except Exception:
        # Create a new bucket if it doesn't exist
        try:
            storage.create_bucket(
                bucket_id=bucket_id,
                name=bucket_name,
                permissions=["read:any"],  # Allow public read access
                file_security=True,
            )
            print(f"Created new bucket: '{bucket_id}'")
        except Exception as e:
            print(f"Error creating bucket: {e}")
            return False
    
    return True

def upload_to_appwrite(storage, file_path, bucket_id="tts_files"):
    """Upload a file to Appwrite storage and return the file URL."""
    if not storage or not os.path.exists(file_path):
        return None
        
    try:
        # Extract filename from path
        file_name = os.path.basename(file_path)
        print(file_path)
        # Upload the file
        result = storage.create_file(
            bucket_id=bucket_id,
            file_id=ID.unique(),
             file=InputFile.from_path(file_path),
            permissions=[Permission.read(Role.any())]  # Allow public read access
        )
        
        # Get file URL
        file_id = result['$id']
        appwrite_endpoint = os.getenv('APPWRITE_ENDPOINT')
        appwrite_project_id = os.getenv('APPWRITE_PROJECT_ID')
        file_url = f"{appwrite_endpoint}/storage/buckets/{bucket_id}/files/{file_id}/view?project={appwrite_project_id}"
        
        print(f"Uploaded file '{file_name}' to Appwrite. File ID: {file_id}")
        return file_url
    
    except Exception as e:
        print(f"Error uploading file '{file_path}': {e}")
        return None

def get_previously_processed_urls():
    """Get a set of all article URLs that have already been processed in previous runs."""
    processed_urls = set()
    
    # Check for the fixed JSON file with processed articles
    articles_json_file = os.path.join("output", "latest_articles.json")
    
    if os.path.exists(articles_json_file):
        try:
            with open(articles_json_file, 'r', encoding='utf-8') as f:
                articles = json.load(f)
                
                # Extract URLs from each article
                for article in articles:
                    if 'url' in article:
                        processed_urls.add(article['url'])
                        
            print(f"Found {len(processed_urls)} previously processed articles from {articles_json_file}")
        except Exception as e:
            print(f"Error reading {articles_json_file}: {e}")
    
    # Also check the links JSON file
    links_json_file = os.path.join("output", "the_hindu_article_links.json")
    
    if os.path.exists(links_json_file):
        try:
            with open(links_json_file, 'r', encoding='utf-8') as f:
                links_data = json.load(f)
                
                # Add all links to processed_urls
                for link in links_data:
                    processed_urls.add(link)
                    
            print(f"Found {len(processed_urls)} total previously processed articles after checking {links_json_file}")
        except Exception as e:
            print(f"Error reading {links_json_file}: {e}")
    
    return processed_urls

def load_article_links_json():
    """Load all article links from the JSON file."""
    links = []
    links_json_file = os.path.join("output", "the_hindu_article_links.json")
    
    if os.path.exists(links_json_file):
        try:
            with open(links_json_file, 'r', encoding='utf-8') as f:
                links = json.load(f)
        except Exception as e:
            print(f"Error reading {links_json_file}: {e}")
    
    return links

def save_article_links_json(all_links):
    """Save all article links to the JSON file."""
    links_json_file = os.path.join("output", "the_hindu_article_links.json")
    
    with open(links_json_file, 'w', encoding='utf-8') as f:
        json.dump(all_links, f, indent=2, ensure_ascii=False)
        
    print(f"Saved all article links to {links_json_file}")

class LatestNewsExtractor:
    def __init__(self):
        self.article_links = []
        self.visited_urls = set()
        self.browser_config = BrowserConfig(
            headless=True,
            verbose=True
        )
        self.seed_url = "https://www.thehindu.com/latest-news/"
        self.max_articles = 5  # Limit to 1 article
        
        # Navigation elements to be removed from content
        self.navigation_text = "Business Agri-Business Economy Industry Markets Budget Children Cities Cities Bengaluru Chennai Coimbatore Delhi Hyderabad Kochi Kolkata Kozhikode Madurai Mangaluru Mumbai Puducherry Thiruvananthapuram Tiruchirapalli Vijayawada Visakhapatnam Data Point Podcast Ebook Education Education Careers Colleges Schools Elections Entertainment Entertainment Art Dance Movies Music Reviews Theatre Environment Food Food Dining Features Guides Recipes Good Health Hunting Monkeypox Life & Style Life & Style Fashion Fitness Homes and gardens Luxury Motoring Travel News News India World States Cities Ground Zero Spotlight Opinion Editorial Cartoon Columns Comment Interview Lead Letters Open Page Corrections & Clarifications Real Estate ISRO Question Corner Society Society Faith History & Culture Sport Cricket Football Hockey Tennis Athletics Motorsport Races Other Sports Between Wickets Specials States States Andhra Pradesh Karnataka Kerala Tamil Nadu Telangana Andaman and Nicobar Islands Arunachal Pradesh Assam Bihar Chandigarh Chhattisgarh Daman, Diu, Dadra and Nagar Haveli Goa Gujarat Haryana Himachal Pradesh Jammu and Kashmir Jharkhand Lakshadweep Ladakh Madhya Pradesh Maharashtra Manipur Meghalaya Mizoram Nagaland Odisha Other States Punjab Rajasthan Sikkim Tripura Uttar Pradesh Uttarakhand West Bengal Decode Karnataka Focus Tamil Nadu Technology Technology Gadgets Internet Visual Story Brandhub"
        
        # Words to remove from content
        self.unwanted_patterns = [
            "LOGIN", "Account", "Search", "Live Now", "SECTION", "TOPICS", 
            "Hindi Belt", "e-Paper", "comments", "premium", "subscribe",
            "sign in", "Events", "Lit for Life", "The Huddle", "Search for topics",
            "people, articles", "Top Picks", "Must Read", "For You", "logout",
            "My account", "Subscription", "Copy link", "Email", "PRINT", "SHARE",
            "Facebook", "Twitter", "LinkedIn", "WhatsApp", "Reddit", "Published:",
            "Updated:", "Follow us:", "Related Topics", "Our code of editorial values",
            "Recommended for you", "Next Story", "This article is closed for comments",
            "Premium", "FREE Trial", "Crossword+", "Have a question?", "Hide", "Show"
        ]
        
        # Common endings that should be removed
        self.article_endings = [
            r"This is a Premium article available exclusively to our subscribers\.",
            r"To read more such articles\.",
            r"To subscribe to The Hindu,",
            r"Our code of editorial values",
            r"This article is closed for comments\.",
            r"Read more news from The Hindu",
            r"Click here to subscribe",
            r"Follow us on",
            r"Get a round-up of the day's top stories in your inbox",
            r"Related Topics",
            r"You have reached your limit for free articles this month",
            r"COMMents",
            r"ADVERTISEMENT"
        ]
        
        # HTTP headers for direct requests
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/search?q=site:thehindu.com",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "TE": "Trailers"
        }
        
        # Create directory structure for images
        self.base_dir = "output"
        self.image_dir = os.path.join(self.base_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)
        
        # Create SSL context for image downloads
        self.ssl_context = ssl._create_unverified_context()
        
        # Minimum image quality requirements
        self.min_width = 400
        self.min_height = 300
        self.min_file_size = 10 * 1024  # 10 KB
        self.allowed_formats = ['.jpg', '.jpeg', '.png']
        
    def is_article_link(self, url):
        """Check if a URL is an article link."""
        if not url or not url.startswith('http'):
            return False
            
        # Must be from thehindu.com domain
        parsed = urlparse(url)
        if not any(domain in parsed.netloc for domain in ['thehindu.com', 'thehindubusinessline.com']):
            return False
            
        # Must end with .ece (article indicator)
        if not url.endswith('.ece'):
            return False
            
        return True
    
    def extract_links(self, content, base_url=None):
        """Extract links from page content."""
        links = []
        
        # Extract markdown-style links [text](URL)
        md_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        for _, url in md_links:
            if url.startswith('http'):
                links.append(url)
            elif base_url and url.startswith('/'):
                links.append(urljoin(base_url, url))
        
        # Extract plain URLs
        url_links = re.findall(r'https?://[^\s\)\]\"\']+', content)
        links.extend(url_links)
        
        # Extract links from HTML-like anchor tags in markdown
        # This handles cases where the markdown might contain HTML
        a_tag_links = re.findall(r'<a[^>]+href=[\'"]([^\'"]+)[\'"][^>]*>', content)
        for url in a_tag_links:
            if url.startswith('http'):
                links.append(url)
            elif base_url and (url.startswith('/') or not url.startswith('http')):
                links.append(urljoin(base_url, url))
        
        # Check if HTML content exists and process with BeautifulSoup
        if '<html' in content.lower():
            try:
                soup = BeautifulSoup(content, 'html.parser')
                for a in soup.find_all('a', href=True):
                    url = a['href']
                    if url.startswith('http'):
                        links.append(url)
                    elif base_url and (url.startswith('/') or not (url.startswith('#') or url.startswith('javascript:'))):
                        links.append(urljoin(base_url, url))
            except Exception as e:
                print(f"Error parsing HTML in content: {e}")
        
        # Remove duplicates and return
        unique_links = list(set(links))
        return unique_links
    
    def clean_content(self, content):
        """Clean the article content by removing navigation, ads, and other non-article elements."""
        try:
            if not content or len(content) < 20:
                return content
                
            # Remove any HTML tags that might remain
            content = re.sub(r'<[^>]+>', ' ', content)
            
            # First detect and handle READ LATER SEE ALL markers 
            read_later_match = re.search(r'READ LATER SEE ALL', content)
            if read_later_match:
                # If we found the marker, check if there's substantial content after it
                parts = content.split("READ LATER SEE ALL", 1)
                if len(parts) > 1 and len(parts[1].strip().split()) > 50:
                    # Use just the content after READ LATER SEE ALL if it's substantial
                    content = parts[1].strip()
                    
            # Handle READ LATER without SEE ALL
            elif "READ LATER" in content:
                parts = content.split("READ LATER", 1)
                if len(parts) > 1 and len(parts[1].strip().split()) > 50:
                    content = parts[1].strip()
            
            # Remove location markers at the beginning (like CHENNAI, NEW DELHI, etc.)
            content = re.sub(r'^[A-Z]{3,}[,:]', '', content)
            
            # Remove date markers at the beginning
            date_pattern = r'^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}'
            content = re.sub(date_pattern, '', content)
            
            # Remove time markers at the beginning
            time_pattern = r'^\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)(?:\s*IST)?'
            content = re.sub(time_pattern, '', content)
            
            # Remove attribution markers at the beginning (like By John Smith, Special Correspondent)
            attribution_pattern = r'^By\s+[A-Za-z.\s]+|^(?:Special Correspondent|Staff Reporter)'
            content = re.sub(attribution_pattern, '', content)
            
            # Split into lines for easier cleaning
            lines = content.split('\n')
            cleaned_lines = []
            
            # Track if we're in main content section
            # Assume we start in main content
            in_main_content = True
            
            # Process each line
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Skip empty lines
                if not line:
                    continue
                
                # Skip common navigation/footer elements
                if any(nav in line.lower() for nav in [
                    'home', 'news', 'sections', 'next story', 'previous story', 
                    'related topics', 'comments', 'share', 'print', 'privacy policy',
                    'terms of use', 'copyright', 'all rights reserved',
                    'advertisement', 'subscribe now', 'sign up', 'login',
                    'read more', 'follow us', 'stay updated'
                ]):
                    continue
                
                # Skip Date/Location/Bureau lines
                if (re.match(r'^[A-Z]{3,}[,:]', line) or 
                    re.match(date_pattern, line) or 
                    re.match(time_pattern, line) or
                    re.match(attribution_pattern, line) or
                    re.match(r'^(Bureau|Correspondent)$', line)):
                    continue
                
                # Skip Photographer credit
                if "Photo Credit:" in line or "File Photo:" in line:
                    continue
                
                # Skip Premium markers
                if "Premium" in line:
                    continue
                
                # Skip very short lines (likely navigation elements)
                if len(line) < 15 and i < 5:
                    continue
                
                # Skip lines that look like single-word navigation
                if len(line.split()) <= 1 and i < 10:
                    continue
                
                # If line contains words like 'paywall', 'subscription', etc., stop processing
                if any(sub in line.lower() for sub in [
                    'paywall', 'subscription', 'subscribe', 'sign in', 
                    'register', 'already have an account'
                ]):
                    break
                
                # Add line to the cleaned content
                cleaned_lines.append(line)
            
            # Join lines into a single content block
            content = '\n'.join(cleaned_lines)
            
            # Perform additional text cleanups
            # Remove READ LATER SEE ALL if somehow it remains
            content = re.sub(r'READ LATER SEE ALL', '', content)
            content = re.sub(r'READ LATER', '', content)
            content = re.sub(r'SEE ALL', '', content)
            
            # Remove "- The Hindu" suffix from any lines
            content = re.sub(r'\s+\-\s+The Hindu', '', content)
            
            # Remove The Hindu Bureau mentions
            content = re.sub(r'The Hindu Bureau', '', content)
            
            # Normalize whitespace
            content = re.sub(r'\s+', ' ', content)
            
            # Final clean of formatting artifacts
            content = re.sub(r'\.{2,}', '.', content)  # Replace multiple periods
            content = re.sub(r'\s+,', ',', content)    # Fix space before comma
            content = re.sub(r'\s+\.', '.', content)   # Fix space before period
            
            return content.strip()
            
        except Exception as e:
            print(f"Error cleaning content: {e}")
            return content
    
    def is_good_image(self, image_content, img_url):
        """Check if an image meets quality requirements."""
        try:
            # Check file size
            if len(image_content) < self.min_file_size:
                print(f"Image too small (size): {img_url} - {len(image_content)} bytes")
                return False
                
            # Check image dimensions and format
            img = Image.open(io.BytesIO(image_content))
            width, height = img.size
            format_lower = img.format.lower() if img.format else ""
            
            # Check dimensions
            if width < self.min_width or height < self.min_height:
                print(f"Image too small (dimensions): {img_url} - {width}x{height}")
                return False
                
            # Check file format - convert PIL format names to extensions
            format_to_ext = {'jpeg': '.jpg', 'jpg': '.jpg', 'png': '.png'}
            ext = format_to_ext.get(format_lower, f".{format_lower}")
            
            if ext not in self.allowed_formats:
                print(f"Image format not allowed: {img_url} - {img.format}")
                return False
                
            return True
            
        except Exception as e:
            print(f"Error checking image quality for {img_url}: {str(e)}")
            return False
    
    def download_image(self, img_url, article_title, position, quality_check=True):
        """Download an image and save it to the images directory."""
        try:
            # Skip SVG files and small images/icons if doing quality check
            parsed_url = urlparse(img_url)
            img_ext = os.path.splitext(parsed_url.path)[1].lower()
            
            if quality_check:
                if img_ext == '.svg':
                    print(f"Skipping SVG image: {img_url}")
                    return None
                    
                if any(x in img_url.lower() for x in ['icon', 'logo', 'spacer', 'pixel', '1x1']):
                    print(f"Skipping icon/tracking image: {img_url}")
                    return None
            
            # Generate a safe filename
            if not img_ext or img_ext not in self.allowed_formats:
                img_ext = ".jpg"  # Default extension if none is found
                
            # Use a hash of the URL to ensure uniqueness
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:10]
            
            # Clean article title for filename
            safe_title = re.sub(r'[^\w\s-]', '', article_title)
            safe_title = re.sub(r'\s+', '_', safe_title)
            safe_title = safe_title[:30]  # Limit title length
            
            # Create filename with position and url hash for uniqueness
            filename = f"{safe_title}_{position}_{url_hash}{img_ext}"
            filepath = os.path.join(self.image_dir, filename)
            
            # Check if file already exists
            if os.path.exists(filepath):
                print(f"Image already exists: {filename}")
                return {
                    'url': img_url,
                    'local_path': filepath,
                    'filename': filename,
                    'position': position
                }
            
            # Download the image content first to check quality
            try:
                # Try with requests first (more robust)
                response = requests.get(img_url, headers=self.headers, verify=False, timeout=10)
                if response.status_code != 200:
                    print(f"Failed to download image: {img_url} - Status code: {response.status_code}")
                    return None
                    
                image_content = response.content
                
                # Check if the image meets quality criteria
                if quality_check and not self.is_good_image(image_content, img_url):
                    return None
                    
                # Save the good image
                with open(filepath, 'wb') as f:
                    f.write(image_content)
                print(f"Downloaded image: {filename}")
                return {
                    'url': img_url,
                    'local_path': filepath,
                    'filename': filename,
                    'position': position
                }
                
            except requests.exceptions.RequestException as e:
                print(f"Request failed for {img_url}: {str(e)}")
                
                # Fallback to urllib if requests fails
                try:
                    req = urllib.request.Request(img_url, headers=self.headers)
                    with urllib.request.urlopen(req, context=self.ssl_context, timeout=10) as response:
                        image_content = response.read()
                        
                        # Check if the image meets quality criteria
                        if quality_check and not self.is_good_image(image_content, img_url):
                            return None
                            
                        # Save the image
                        with open(filepath, 'wb') as f:
                            f.write(image_content)
                        print(f"Downloaded image (fallback): {filename}")
                        return {
                            'url': img_url,
                            'local_path': filepath,
                            'filename': filename,
                            'position': position
                        }
                except Exception as e:
                    print(f"Failed to download image with urllib: {e}")
                    return None
                
        except Exception as e:
            print(f"Error downloading image {img_url}: {str(e)}")
            return None
    
    def extract_content_from_url(self, url):
        """Extract article content from a given URL."""
        try:
            # Make a request to the article URL
            response = requests.get(url, headers=self.headers, verify=False, timeout=30)
            
            if response.status_code != 200:
                print(f"Failed to fetch article: {url} - Status code: {response.status_code}")
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract the headline
            headline_elem = soup.select_one('h1.title')
            if headline_elem:
                headline = headline_elem.get_text().strip()
            else:
                # Fallback to other possible headline elements
                headline_elem = soup.select_one('.article-title, .title, h1')
                headline = headline_elem.get_text().strip() if headline_elem else "Unknown Headline"
            
            # Extract the summary/content
            content_elems = soup.select('.content, .article p, article p, [itemprop="articleBody"] p')
            content = ' '.join(elem.get_text().strip() for elem in content_elems)
            content = self.clean_content(content)
            
            # Ensure we have at least some content/summary
            if not content:
                # Try alternate content selectors
                content_elems = soup.select('p')
                content = ' '.join(elem.get_text().strip() for elem in content_elems)
                content = self.clean_content(content)
                
            # If still no content, use a default summary with the headline
            if not content:
                content = f"Article about {headline}. No detailed content could be extracted."
                
            summary = content[:1000]  # Just use the first 1000 chars as summary
            
            # Extract the date
            date_elem = soup.select_one('meta[itemprop="datePublished"]')
            if date_elem and date_elem.get('content'):
                date = date_elem['content'].split('T')[0]  # Get just the date part
            else:
                date = datetime.now().strftime("%Y-%m-%d")
            
            # Extract the time
            time_elem = soup.select_one('meta[itemprop="datePublished"]')
            if time_elem and time_elem.get('content') and 'T' in time_elem['content']:
                time_str = time_elem['content'].split('T')[1]
                if '+' in time_str:  # Handle format like "2023-04-03T14:30:00+05:30"
                    time_str = time_str.split('+')[0]
                time_str = time_str[:8]  # Keep only HH:MM:SS
            else:
                time_str = datetime.now().strftime("%H:%M:%S")
            
            # Extract the author
            author_elem = soup.select_one('meta[name="author"]')
            author = author_elem['content'] if author_elem and author_elem.get('content') else "Unknown Author"
            
            # Extract the source
            source = "The Hindu"
            
            # Extract the category
            category_elems = soup.select('.breadcrumb li')
            categories = [elem.get_text().strip() for elem in category_elems if elem.get_text().strip()]
            category = categories[-1] if categories else "General"
            
            # Extract tags/keywords
            tag_elems = soup.select('meta[name="keywords"]')
            tags = []
            for tag_elem in tag_elems:
                if tag_elem.get('content'):
                    # Split by commas and clean up each tag
                    tags.extend([tag.strip() for tag in tag_elem['content'].split(',') if tag.strip()])
            
            if not tags:
                # Try alternate tag locations
                tag_elems = soup.select('.tags a, .article-tags a')
                tags = [tag.get_text().strip() for tag in tag_elems if tag.get_text().strip()]
            
            # Get images
            main_image_url = None
            image_urls = []
            
            # Try to find the main image
            main_image = soup.select_one('meta[property="og:image"]')
            if main_image and main_image.get('content'):
                main_image_url = main_image['content']
                image_urls.append(main_image_url)
            
            # Get additional images from the article
            img_elems = soup.select('.article img, article img, [itemprop="articleBody"] img')
            for img in img_elems:
                if img.get('src'):
                    img_url = img['src']
                    # Make sure URL is absolute
                    if not img_url.startswith('http'):
                        img_url = urljoin(url, img_url)
                    if img_url not in image_urls:
                        image_urls.append(img_url)
            
            # Download and save images
            saved_images = []
            main_image_filename = None
            
            # # Download and save images - COMMENTED OUT
            saved_images = []
            main_image_filename = None
            
            for img_url in image_urls:
                filename = self.download_image(img_url, headline, 0, quality_check=False)
                if filename:
                    saved_images.append(filename)
                    if img_url == main_image_url:
                        main_image_filename = filename
            
            # Set main image to first saved image if no main image was found
            if not main_image_filename and saved_images:
                main_image_filename = saved_images[0]
            
            # Generate a unique article ID based on URL and content hash
            article_id = hashlib.md5((url + headline).encode()).hexdigest()[:12]
            
            # Create article data structure
            article_data = {
                'article_id': article_id,  # Add unique article ID
                'url': url,
                'headline': headline,
                'summary': summary,
                'content': content[:5000],  # Limit content to 5000 chars
                'date': date,
                'time': time_str,
                'author': author,
                'source': source,
                'category': category,
                'tags': tags,
                'language': 'en'  # Default language is English
            }
            
            # Add image information if available
            if main_image_filename:
                article_data['main_image'] = main_image_filename
            
            if saved_images:
                article_data['images'] = saved_images
            
            return article_data
            
        except Exception as e:
            print(f"Error extracting content from {url}: {str(e)}")
            return None
            
    def extract_latest_articles(self):
        """Extract latest news articles from The Hindu website using direct HTTP requests."""
        print("Extracting latest articles using direct request...")
        
        try:
            # Get a set of previously processed URLs
            previously_processed = get_previously_processed_urls()
            print(f"Found {len(previously_processed)} previously processed articles")
            
            # Get the latest news page
            response = requests.get(self.seed_url, headers=self.headers, verify=False)
            
            if response.status_code != 200:
                print(f"Failed to fetch latest news page: {self.seed_url} - Status code: {response.status_code}")
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract links from the latest news page
            raw_links = []
            for a in soup.find_all('a', href=True):
                raw_links.append(a['href'])
                
            # Clean and filter links to get article links
            article_links = []
            processed_in_batch = set()  # Track URLs we've already added in this batch
            
            for link in raw_links:
                # Make sure URL is absolute
                if not link.startswith('http'):
                    link = urljoin(self.seed_url, link)
                    
                # Only add if it's an article link, hasn't been processed before, and not already in our batch
                if self.is_article_link(link) and link not in previously_processed and link not in processed_in_batch:
                    article_links.append(link)
                    processed_in_batch.add(link)
            
            print(f"Found {len(article_links)} new article links")
            
            # Load existing links from JSON
            all_links = load_article_links_json()
            
            # Add new links to the collection (avoiding duplicates)
            for link in article_links:
                if link not in all_links:
                    all_links.append(link)
            
            # Save all links back to JSON
            save_article_links_json(all_links)
            
            # Process each article link
            articles = []
            max_articles = min(55, len(article_links)) if self.max_articles == 0 else min(self.max_articles, len(article_links))
            
            for i, url in enumerate(article_links[:max_articles], 1):
                print(f"Processing article {i}/{max_articles}: {url}")
                article = self.extract_content_from_url(url)
                if article:
                    articles.append(article)
                    print(f"✓ Successfully processed article {i}/{max_articles}")
                else:
                    print(f"✗ Failed to process article {i}/{max_articles}")
            
            print(f"Successfully extracted {len(articles)} articles out of {max_articles} links")
            return articles
            
        except Exception as e:
            print(f"Error extracting latest articles: {str(e)}")
            return []

# Add function to generate voice file for summary
def generate_voice_file(article_data):
    """Generate a voice file for the article summary and return the file path."""
    if not credentials:
        print("Skipping voice generation: No credentials available")
        return None
        
    try:
        # Get the summary text
        summary = article_data.get('summary', '')
        if not summary:
            print("Skipping voice generation: No summary available")
            return None
            
        # Use English as default language or get from article if available
        language_code = article_data.get('language', 'en')
        
        # Check if language code has correct format, if not use default
        if language_code not in INDIAN_LANGUAGES:
            language_code = 'en'
            
        # Get the TTS language code
        tts_language_code = INDIAN_LANGUAGES[language_code]['tts_code']
        
        # Create TTS client
        client = texttospeech.TextToSpeechClient(credentials=credentials)
        
        # Get the voice name
        voice_name = f"{tts_language_code}-Chirp3-HD-Kore"
        
        # Set up the input
        synthesis_input = texttospeech.SynthesisInput(text=summary)
        
        # Set up the voice
        voice = texttospeech.VoiceSelectionParams(
            language_code=tts_language_code,
            name=voice_name
        )
        
        # Set up the audio config
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            effects_profile_id=["high-quality-studio"]
        )
        
        print(f"Generating speech for article: {article_data.get('headline', '')[:30]}...")
        try:
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
        except Exception as e:
            print(f"Error with specific voice {voice_name}, trying generic voice: {e}")
            # Fallback to generic voice selection
            voice = texttospeech.VoiceSelectionParams(
                language_code=tts_language_code
            )
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            print(f"Successfully generated speech with generic voice for {tts_language_code}")
        
        # Create output directory for the language
        lang_dir = INDIAN_LANGUAGES[language_code]['name']
        voice_dir = os.path.join("output", "voice", lang_dir)
        os.makedirs(voice_dir, exist_ok=True)
        
        # Get article ID from article data or generate a new one if not available
        article_id = article_data.get('article_id')
        if not article_id:
            article_id = hashlib.md5(article_data.get('url', '').encode()).hexdigest()[:12]
            
        # Get the first two letters of the language code
        lang_prefix = language_code[:2]
        
        # Create output path with format: [language_code]_[article_id].mp3
        output_file = os.path.join(voice_dir, f"{lang_prefix}_{article_id}.mp3")
        
        # Write the audio content
        with open(output_file, "wb") as out:
            out.write(response.audio_content)
        
        print(f"Audio content written to '{output_file}'")
        
        # Return the relative path for storage in JSON
        return os.path.relpath(output_file)
    except Exception as e:
        print(f"Error generating voice file: {e}")
        return None

# Add main entry point to make the script executable
def main():
    """Main function to run the extractor."""
    print("Running LatestNewsExtractor...")
    extractor = LatestNewsExtractor()
    
    # Create output directory
    os.makedirs(extractor.base_dir, exist_ok=True)
    
    # Extract the latest articles using direct request method
    print("Extracting latest articles...")
    articles = extractor.extract_latest_articles()
    
    if articles:
        print(f"Successfully extracted {len(articles)} articles")
        
        # Initialize Appwrite for uploading TTS files
        client, storage = initialize_appwrite()
        appwrite_available = False
        
        if client and storage:
            appwrite_available = create_bucket_if_not_exists(storage)
            if appwrite_available:
                print("Appwrite successfully initialized for TTS uploads")
            else:
                print("Warning: Appwrite initialization failed, will proceed without uploading")
        
        # Track which files were successfully uploaded
        successfully_uploaded_files = []
        
        # Generate voice files for each article
        print("Generating voice files for article summaries...")
        for article in articles:
            # Ensure the article has an article_id
            if 'article_id' not in article:
                # Generate a unique article ID based on URL and headline
                article['article_id'] = hashlib.md5((article.get('url', '') + article.get('headline', '')).encode()).hexdigest()[:12]
            
            # Set default language if not present
            if 'language' not in article:
                article['language'] = 'en'
                
            voice_file = generate_voice_file(article)
            if voice_file:
                article['voice_file'] = voice_file
                
                # If Appwrite is available, upload the file and add URL to article
                if appwrite_available:
                    try:
                        file_url = upload_to_appwrite(storage, voice_file)
                        if file_url:
                            article['voice_file_url'] = file_url
                            print(f"Added Appwrite URL to article: {article.get('headline', '')[:30]}")
                            # Mark file for deletion after successful upload
                            successfully_uploaded_files.append(voice_file)
                    except Exception as e:
                        print(f"Error uploading to Appwrite: {e}")
        
        # Save articles to output directory with a fixed filename (replacing previous file)
        output_file = os.path.join(extractor.base_dir, "latest_articles.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
            
        print(f"Articles saved to {output_file}")
        
        # If there are voice files but Appwrite wasn't available, try uploading with requests
        if not appwrite_available and any('voice_file' in article and not article.get('voice_file_url') for article in articles):
            print("Appwrite SDK upload failed. Attempting upload via direct HTTP requests...")
            try:
                # Check if required packages are available
                import requests
                import uuid
                
                # Load credentials from environment
                appwrite_endpoint = os.getenv('APPWRITE_ENDPOINT')
                appwrite_project_id = os.getenv('APPWRITE_PROJECT_ID')
                appwrite_api_key = os.getenv('APPWRITE_API_KEY')
                bucket_id = os.getenv('APPWRITE_AUDIO_BUCKET_ID', 'tts_files')
                
                if all([appwrite_endpoint, appwrite_project_id, appwrite_api_key]):
                    print("Found Appwrite credentials in environment. Attempting direct HTTP upload...")
                    
                    # Track uploaded files for summary
                    updated_articles = 0
                    uploaded_files = []
                    
                    # Process each article with voice file
                    for article in articles:
                        if 'voice_file' in article and not article.get('voice_file_url'):
                            voice_file = article['voice_file']
                            
                            # Check if the file exists
                            if os.path.exists(voice_file):
                                print(f"Uploading voice file for article: {article.get('headline', '')[:30]}...")
                                
                                # Get file name from path
                                file_name = os.path.basename(voice_file)
                                file_id = str(uuid.uuid4())
                                
                                # Prepare request
                                url = f"{appwrite_endpoint}/storage/buckets/{bucket_id}/files"
                                
                                headers = {
                                    'X-Appwrite-Project': appwrite_project_id,
                                    'X-Appwrite-Key': appwrite_api_key
                                }
                                
                                # Upload file
                                try:
                                    with open(voice_file, 'rb') as file_content:
                                        data = {
                                            'fileId': file_id
                                        }
                                        
                                        files = {
                                            'file': (file_name, file_content, 'audio/mpeg')
                                        }
                                        
                                        # Make the request
                                        response = requests.post(url, headers=headers, data=data, files=files)
                                        
                                        # Check response
                                        if response.status_code == 201 or response.status_code == 200:
                                            # Create public URL
                                            file_url = f"{appwrite_endpoint}/storage/buckets/{bucket_id}/files/{file_id}/view?project={appwrite_project_id}"
                                            print(f"Successfully uploaded {file_name}. URL: {file_url}")
                                            
                                            # Update article with URL
                                            article['voice_file_url'] = file_url
                                            updated_articles += 1
                                            
                                            # Track successful uploads
                                            uploaded_files.append({
                                                'article_id': article.get('article_id', ''),
                                                'filename': file_name,
                                                'url': file_url
                                            })
                                            
                                            # Mark file for deletion after successful upload
                                            successfully_uploaded_files.append(voice_file)
                                        else:
                                            print(f"Error uploading {file_name}. Status code: {response.status_code}")
                                            print(f"Response: {response.text}")
                                
                                except Exception as e:
                                    print(f"Exception uploading {file_name}: {str(e)}")
                    
                    # If any articles were updated, save the file again
                    if updated_articles > 0:
                        # Save updated articles
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(articles, f, indent=2, ensure_ascii=False)
                        print(f"Updated {updated_articles} articles with voice file URLs.")
                        
                        # Save a separate file with just the uploaded URLs
                        if uploaded_files:
                            urls_file = os.path.join(extractor.base_dir, "voice_urls.json")
                            with open(urls_file, 'w', encoding='utf-8') as f:
                                json.dump(uploaded_files, f, indent=2, ensure_ascii=False)
                            print(f"Saved {len(uploaded_files)} voice file URLs to {urls_file}")
                else:
                    print("Missing required Appwrite credentials in environment variables.")
            except ImportError:
                print("Could not import required packages for HTTP upload. Install 'requests' package.")
            except Exception as e:
                print(f"Error during HTTP upload attempt: {e}")
        
        # Delete successfully uploaded audio files to save space
        if successfully_uploaded_files:
            print(f"Cleaning up {len(successfully_uploaded_files)} successfully uploaded audio files...")
            for file_path in successfully_uploaded_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Deleted: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")
            print("Cleanup completed.")
    else:
        print("No articles were extracted")

if __name__ == "__main__":
    main()
