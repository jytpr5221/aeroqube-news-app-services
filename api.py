import os
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from latest_extractor import LatestNewsExtractor, initialize_appwrite, upload_to_appwrite
from google.cloud import texttospeech
from google.oauth2 import service_account
import shutil
import atexit


# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("api")

creds_path = os.path.join("tmp", "google_creds.json")
creds_json = os.getenv("GOOGLE_CREDENTIALS")
if not creds_json:
    logger.error("GOOGLE_CREDENTIALS not found in environment variables.")
    raise ValueError("Missing GOOGLE_CREDENTIALS")

with open(creds_path, "w") as f:
    f.write(creds_json)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path


# Set up TTS credentials
credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if os.path.exists(credentials_path):
    credentials = service_account.Credentials.from_service_account_file(credentials_path)
else:
    # logger.log(credentials_path)
    logger.warning(f"Warning: TTS credentials file not found at {credentials_path}")
    credentials = None

def cleanup_creds():
    if os.path.exists(creds_path):
        try:
            # Clear the contents instead of removing the file
            with open(creds_path, "w") as f:
                f.write("")
            logger.info(f"Cleared temp credentials file: {creds_path}")
        except Exception as e:
            logger.warning(f"Failed to clear temp creds file: {e}")

atexit.register(cleanup_creds)

from translate import translate_article

# Initialize Appwrite client and storage
appwrite_client, appwrite_storage = initialize_appwrite()
APPWRITE_AUDIO_BUCKET_ID = os.getenv('APPWRITE_AUDIO_BUCKET_ID')

# Map of Indian languages with their codes and TTS codes
INDIAN_LANGUAGES = {
    'as': {'name': 'Assamese', 'tts_code': 'as-IN'},
    'bn': {'name': 'Bengali', 'tts_code': 'bn-IN'},
    'bho': {'name': 'Bhojpuri', 'tts_code': 'hi-IN'},
    'gu': {'name': 'Gujarati', 'tts_code': 'gu-IN'},
    'hi': {'name': 'Hindi', 'tts_code': 'hi-IN'},
    'kn': {'name': 'Kannada', 'tts_code': 'kn-IN'},
    'kok': {'name': 'Konkani', 'tts_code': 'hi-IN'},
    'mai': {'name': 'Maithili', 'tts_code': 'hi-IN'},
    'ml': {'name': 'Malayalam', 'tts_code': 'ml-IN'},
    'mni-Mtei': {'name': 'Manipuri', 'tts_code': 'en-IN'},
    'mr': {'name': 'Marathi', 'tts_code': 'mr-IN'},
    'or': {'name': 'Odia', 'tts_code': 'or-IN'},
    'pa': {'name': 'Punjabi', 'tts_code': 'pa-IN'},
    'sa': {'name': 'Sanskrit', 'tts_code': 'hi-IN'},
    'sd': {'name': 'Sindhi', 'tts_code': 'hi-IN'},
    'ta': {'name': 'Tamil', 'tts_code': 'ta-IN'},
    'te': {'name': 'Telugu', 'tts_code': 'te-IN'},
    'ur': {'name': 'Urdu', 'tts_code': 'hi-IN'},
    'en': {'name': 'English_Indian', 'tts_code': 'en-IN'}
}

# Global cache for articles
article_cache = {
    "last_updated": None,
    "articles": [],
    "processing": False
}

def generate_voice_file(text, lang_code, article_id):
    """Generate a voice file for the text in specified language and return the file URL"""
    if not credentials:
        logger.warning("Skipping voice generation: No credentials available")
        return None
        
    try:
        # Check if language is supported for TTS
        if lang_code not in INDIAN_LANGUAGES:
            logger.warning(f"Skipping voice generation: Language {lang_code} not supported")
            return None
            
        # Get the TTS language code
        tts_language_code = INDIAN_LANGUAGES[lang_code]['tts_code']
        
        # Create TTS client
        client = texttospeech.TextToSpeechClient(credentials=credentials)
        
        # Get the voice name - Chirp3 HD or Kore voices are high quality
        voice_name = f"{tts_language_code}-Chirp3-HD-Kore"
        
        # Set up the input
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
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
        
        logger.info(f"Generating speech for article {article_id} in {lang_code}")
        
        # Try with specific voice, with fallback options
        try:
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
        except Exception as e:
            logger.warning(f"Error with specific voice {voice_name}, trying generic voice: {e}")
            # Fallback to generic voice selection
            voice = texttospeech.VoiceSelectionParams(
                language_code=tts_language_code
            )
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
        
        # Create article language directory
        article_lang_dir = os.path.join("output", "translations", "articles", article_id, lang_code)
        os.makedirs(article_lang_dir, exist_ok=True)
        
        # Create output path
        output_file = os.path.join(article_lang_dir, "voice.mp3")
        
        # Write the audio content
        with open(output_file, "wb") as out:
            out.write(response.audio_content)
        
        # Upload to Appwrite and get URL
        file_url = upload_to_appwrite(appwrite_storage, output_file, APPWRITE_AUDIO_BUCKET_ID)
        
        # Save voice metadata
        voice_metadata = {
            "article_id": article_id,
            "language": lang_code,
            "language_name": INDIAN_LANGUAGES[lang_code]['name'],
            "file_path": output_file,
            "appwrite_url": file_url,
            "created_at": datetime.now().isoformat()
        }
        
        with open(os.path.join(article_lang_dir, "voice_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(voice_metadata, f, indent=2, ensure_ascii=False)
        
        return file_url
    
    except Exception as e:
        logger.error(f"Error generating speech: {e}")
        return None

def process_article(article, target_languages):
    """Process a single article: summarize, translate, and generate TTS"""
    article_id = article.get('article_id')
    
    # Add English summary and TTS
    english_summary = article.get('summary', article.get('content', '')[:1000])
    if english_summary:
        # Generate English voice file
        en_voice_url = generate_voice_file(english_summary, 'en', article_id)
        if en_voice_url:
            article['en_voice_url'] = en_voice_url
    
    # Process translations for each language
    article['translations'] = {}
    for lang_code in target_languages:
        if lang_code == 'en':
            continue  # Skip English as it's already processed
            
        try:
            # Translate the article
            translated_article = translate_article(article, lang_code)
            
            if translated_article:
                # Generate voice file for translated summary
                translated_summary = translated_article.get('summary', '')
                if translated_summary:
                    voice_url = generate_voice_file(translated_summary, lang_code, article_id)
                    
                    # Store translation data
                    article['translations'][lang_code] = {
                        'title': translated_article.get('headline', ''),
                        'summary': translated_summary,
                        'voice_url': voice_url
                    }
        except Exception as e:
            logger.error(f"Error processing article {article_id} for language {lang_code}: {e}")
    
    return article

def extract_and_process(languages=None):
    """Extract articles and process them asynchronously"""
    try:
        # Set global flag to indicate processing
        article_cache["processing"] = True
        
        # Initialize extractor
        extractor = LatestNewsExtractor()
        
        # Extract articles
        extracted_articles = extractor.extract_latest_articles()
        
        # Ensure output directory exists
        os.makedirs("output", exist_ok=True)
        
        # Save extracted articles to JSON file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join("output", f"latest_articles_{timestamp}.json")
        output_file = os.path.join("output", "latest_articles.json")
        
        # Save a timestamped backup
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_articles, f, indent=2, ensure_ascii=False)
            
        # Save to the main file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_articles, f, indent=2, ensure_ascii=False)
            
        # Process articles and add to cache
        for article in extracted_articles:
            # Generate English voice file first
            english_summary = article.get('summary', article.get('content', '')[:1000])
            if english_summary:
                # Generate English voice file
                en_voice_url = generate_voice_file(english_summary, 'en', article.get('article_id', ''))
                if en_voice_url:
                    article['en_voice_url'] = en_voice_url
            
            # Initialize translations dictionary
            article['translations'] = {}
        
        # Update the global cache
        article_cache["articles"] = extracted_articles
        article_cache["last_updated"] = datetime.now().isoformat()
        
        # Create translations directory structure
        os.makedirs("output/translations", exist_ok=True)
        os.makedirs("output/translations/articles", exist_ok=True)
        
        # Determine which languages to process
        if languages:
            # Process specific languages if provided
            language_list = [lang.strip() for lang in languages.split(',') if lang.strip()]
        else:
            # Process all supported languages if none specified
            language_list = list(INDIAN_LANGUAGES.keys())
        
        # Keep track of translations to be saved
        saved_translations = {}
        
        # Process each article completely (all translations) before moving to the next
        for article in article_cache["articles"]:
            article_id = article.get('article_id', '')
            if not article_id:
                continue
                
            logger.info(f"Processing all translations for article {article_id}")
            
            # Create article directory
            article_dir = os.path.join("output", "translations", "articles", article_id)
            os.makedirs(article_dir, exist_ok=True)
            
            # Save article metadata
            with open(os.path.join(article_dir, "article_metadata.json"), 'w', encoding='utf-8') as f:
                article_metadata = {
                    "article_id": article_id,
                    "headline": article.get('headline', ''),
                    "url": article.get('url', ''),
                    "date": article.get('date', ''),
                    "time": article.get('time', ''),
                    "category": article.get('category', ''),
                    "languages": []
                }
                json.dump(article_metadata, f, indent=2, ensure_ascii=False)
            
            # Process each language for this article
            for lang_code in language_list:
                if lang_code not in INDIAN_LANGUAGES:
                    logger.warning(f"Skipping unsupported language: {lang_code}")
                    continue
                
                # Skip if article already has this translation
                if 'translations' in article and lang_code in article['translations']:
                    logger.info(f"Article {article_id} already has {lang_code} translation")
                    
                    # Still update the article directory structure
                    lang_dir = os.path.join(article_dir, lang_code)
                    os.makedirs(lang_dir, exist_ok=True)
                    
                    # Save translation data
                    trans_data = article['translations'][lang_code]
                    with open(os.path.join(lang_dir, "translation.json"), 'w', encoding='utf-8') as f:
                        json.dump(trans_data, f, indent=2, ensure_ascii=False)
                    
                    # Update article metadata to include this language
                    article_metadata["languages"].append(lang_code)
                    continue
                
                try:
                    logger.info(f"Translating article {article_id} to {lang_code}")
                    
                    # Create language directory
                    lang_dir = os.path.join(article_dir, lang_code)
                    os.makedirs(lang_dir, exist_ok=True)
                    
                    # Translate article
                    translated_article = translate_article(article, lang_code)
                    
                    # Generate voice file for translation
                    translated_summary = translated_article.get('summary', '')
                    voice_url = None
                    
                    if translated_summary:
                        voice_url = generate_voice_file(translated_summary, lang_code, article_id)
                    
                    # Store translation data
                    translation_data = {
                        'title': translated_article.get('headline', ''),
                        'summary': translated_summary,
                        'voice_url': voice_url,
                        'article_id': article_id,
                        'language': lang_code,
                        'language_name': INDIAN_LANGUAGES[lang_code]['name'],
                        'translated_at': datetime.now().isoformat()
                    }
                    
                    # Save the translation data to the article
                    article['translations'][lang_code] = translation_data
                    
                    # Save translation to language directory
                    with open(os.path.join(lang_dir, "translation.json"), 'w', encoding='utf-8') as f:
                        json.dump(translation_data, f, indent=2, ensure_ascii=False)
                    
                    # Update article metadata to include this language
                    article_metadata["languages"].append(lang_code)
                    
                    # Keep track of this article in our language summary
                    if lang_code not in saved_translations:
                        saved_translations[lang_code] = []
                    saved_translations[lang_code].append(article_id)
                    
                    logger.info(f"Successfully translated article {article_id} to {lang_code}")
                    
                except Exception as e:
                    logger.error(f"Error translating article {article_id} to {lang_code}: {e}")
            
            # Update article metadata file with all languages
            with open(os.path.join(article_dir, "article_metadata.json"), 'w', encoding='utf-8') as f:
                json.dump(article_metadata, f, indent=2, ensure_ascii=False)
        
        # Save updated articles with translations
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(article_cache["articles"], f, indent=2, ensure_ascii=False)
        
        # Create languages summary
        languages_summary = {}
        for lang_code, article_ids in saved_translations.items():
            languages_summary[lang_code] = {
                'name': INDIAN_LANGUAGES[lang_code]['name'],
                'tts_supported': INDIAN_LANGUAGES[lang_code]['tts_code'] is not None,
                'article_count': len(article_ids),
                'article_ids': article_ids
            }
        
        # Add any languages that weren't processed
        for lang_code in INDIAN_LANGUAGES:
            if lang_code not in languages_summary:
                languages_summary[lang_code] = {
                    'name': INDIAN_LANGUAGES[lang_code]['name'],
                    'tts_supported': INDIAN_LANGUAGES[lang_code]['tts_code'] is not None,
                    'article_count': 0,
                    'article_ids': []
                }
        
        # Save languages summary
        translations_summary_file = os.path.join("output", "translations", "languages.json")
        with open(translations_summary_file, 'w', encoding='utf-8') as f:
            json.dump(languages_summary, f, indent=2, ensure_ascii=False)
        
        # Set flag to indicate processing is complete
        article_cache["processing"] = False
        
        logger.info(f"Extraction and processing complete. {len(extracted_articles)} articles processed with {len(language_list)} languages.")
        
    except Exception as e:
        logger.error(f"Error in extraction process: {e}")
        article_cache["processing"] = False

@app.route("/")
def index():
    return "✅ Flask server is running on Render!"


@app.route('/extract', methods=['POST'])
def extract_news():
    """
    Extract news articles, summarize, translate, and generate TTS
    Optional parameters:
    - languages: Comma-separated list of language codes to translate to
    - background: If 'true', run in background thread (default: 'true')
    """
    # Get parameters
    languages = request.args.get('languages')
    background = request.args.get('background', 'true').lower() == 'true'
    
    # Check if already processing
    if article_cache["processing"]:
        return jsonify({
            "status": "already_processing",
            "message": "News extraction is already in progress"
        }), 409
    
    # Start extraction process
    if background:
        # Run in background thread
        thread = threading.Thread(target=extract_and_process, args=(languages,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "status": "processing",
            "message": "News extraction started in background",
            "languages": languages or "all"
        })
    else:
        # Run synchronously
        extract_and_process(languages)
        
        return jsonify({
            "status": "completed",
            "message": "News extraction completed",
            "languages": languages or "all",
            "article_count": len(article_cache["articles"]),
            "last_updated": article_cache["last_updated"]
        })

def organize_translations_by_article_id():
    """
    Generate a summary of all translations organized by article ID and language.
    """
    try:
        # Create a dictionary to track translations by language
        translations_by_lang = {}
        
        # Initialize with all supported languages
        for lang_code, lang_info in INDIAN_LANGUAGES.items():
            translations_by_lang[lang_code] = {
                'name': lang_info['name'],
                'tts_supported': lang_info['tts_code'] is not None,
                'article_count': 0,
                'article_ids': []
            }
        
        # Check if articles directory exists
        articles_dir = os.path.join("output", "translations", "articles")
        if not os.path.exists(articles_dir):
            logger.warning(f"Articles directory not found at {articles_dir}")
            return translations_by_lang
        
        # Iterate through all article directories
        for article_id in os.listdir(articles_dir):
            article_dir = os.path.join(articles_dir, article_id)
            if not os.path.isdir(article_dir):
                continue
                
            # Get languages for this article
            for lang_code in os.listdir(article_dir):
                lang_dir = os.path.join(article_dir, lang_code)
                if not os.path.isdir(lang_dir) or lang_code not in translations_by_lang:
                    continue
                
                # Count this as a translation
                if article_id not in translations_by_lang[lang_code]['article_ids']:
                    translations_by_lang[lang_code]['article_ids'].append(article_id)
                    translations_by_lang[lang_code]['article_count'] += 1
        
        # Save languages summary
        translations_summary_file = os.path.join("output", "translations", "languages.json")
        with open(translations_summary_file, 'w', encoding='utf-8') as f:
            json.dump(translations_by_lang, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Generated translations summary. Summary saved to {translations_summary_file}")
        return translations_by_lang
            
    except Exception as e:
        logger.error(f"Error organizing translations: {e}")
        return {}

def get_structured_articles(articles, language=None):
    """
    Structure articles according to the requested format, with translations organized by language.
    
    Args:
        articles: List of articles to structure
        language: Optional specific language to include
        
    Returns:
        List of articles with structured translations
    """
    structured_articles = []
    base_url = request.url_root.rstrip('/')
    
    for article in articles:
        # Basic article structure
        structured_article = {
            'article_id': article.get('article_id', ''),
            'url': article.get('url', ''),
            'headline': article.get('headline', ''),
            'summary': article.get('summary', ''),
            'content': article.get('content', ''),
            'date': article.get('date', ''),
            'time': article.get('time', ''),
            'author': article.get('author', ''),
            'source': article.get('source', ''),
            'category': article.get('category', ''),
            'tags': article.get('tags', []),
            'language': 'en'  # Default language is English
        }
        
        # Add English voice URL if available
        if 'en_voice_url' in article:
            structured_article['appwrite_audio_url'] = article['en_voice_url']
            structured_article['tts_file_path'] = article.get('voice_file', '')
        elif 'voice_file_url' in article:
            structured_article['appwrite_audio_url'] = article['voice_file_url']
            structured_article['tts_file_path'] = article.get('voice_file', '')
        else:
            structured_article['appwrite_audio_url'] = None
            structured_article['tts_file_path'] = ''
            
        # Process main image
        main_image_data = None
        if 'main_image' in article and article['main_image']:
            main_image = article['main_image']
            # Check different possible formats of main_image
            if isinstance(main_image, dict):
                # If it's already a dictionary with metadata
                img_copy = main_image.copy()
                if 'filename' in img_copy:
                    img_copy['server_url'] = f"{base_url}/images/{img_copy['filename']}"
                structured_article['main_image'] = img_copy
                main_image_data = img_copy
            elif isinstance(main_image, str):
                # If it's just a filename string
                main_image_data = {
                    'url': article.get('url', ''),
                    'local_path': f"output/images/{main_image}",
                    'filename': main_image,
                    'position': 0,
                    'server_url': f"{base_url}/images/{main_image}"
                }
                structured_article['main_image'] = main_image_data
        
        # Process article images
        structured_images = []
        if 'images' in article and article['images']:
            # Check and handle different formats of images array
            for idx, img in enumerate(article['images']):
                if isinstance(img, dict):
                    # If it's already a dictionary with metadata
                    img_copy = img.copy()
                    if 'filename' in img_copy:
                        img_copy['server_url'] = f"{base_url}/images/{img_copy['filename']}"
                    elif 'local_path' in img_copy:
                        # Extract filename from path
                        filename = os.path.basename(img_copy['local_path'])
                        img_copy['filename'] = filename
                        img_copy['server_url'] = f"{base_url}/images/{filename}"
                    structured_images.append(img_copy)
                elif isinstance(img, str):
                    # If it's just a filename string
                    structured_images.append({
                        'url': article.get('url', ''),
                        'local_path': f"output/images/{img}",
                        'filename': img,
                        'position': idx,
                        'server_url': f"{base_url}/images/{img}"
                    })
            
            structured_article['images'] = structured_images
            
        # Process translations
        structured_article['translations'] = {}
        
        if 'translations' in article:
            # If specific language requested, only include that
            if language and language != 'en':
                if language in article['translations']:
                    trans_data = article['translations'][language]
                    # Create a full translation object with all necessary fields
                    structured_article['translations'][language] = {
                        'article_id': article.get('article_id', ''),
                        'author': article.get('author', ''),
                        'category': article.get('category', ''),
                        'headline': trans_data.get('title', ''),
                        'title': trans_data.get('title', ''),
                        'summary': trans_data.get('summary', ''),
                        'source': article.get('source', ''),
                        'tags': article.get('tags', []),
                        'language': language,
                        'language_name': INDIAN_LANGUAGES.get(language, {}).get('name', ''),
                        'appwrite_audio_url': trans_data.get('voice_url'),
                        'tts_file_path': None
                    }
                    
                    # Remove main_image from translation
                    if main_image_data:
                        structured_article['translations'][language].pop('main_image', None)
            else:
                # Include all translations
                for lang, trans_data in article['translations'].items():
                    # Create a full translation object with all necessary fields
                    structured_article['translations'][lang] = {
                        'article_id': article.get('article_id', ''),
                        'author': article.get('author', ''),
                        'category': article.get('category', ''),
                        'headline': trans_data.get('title', ''),
                        'title': trans_data.get('title', ''),
                        'summary': trans_data.get('summary', ''),
                        'source': article.get('source', ''),
                        'tags': article.get('tags', []),
                        'language': lang,
                        'language_name': INDIAN_LANGUAGES.get(lang, {}).get('name', ''),
                        'appwrite_audio_url': trans_data.get('voice_url'),
                        'tts_file_path': None
                    }
                    
                    # Remove main_image from translation
                    if main_image_data:
                        structured_article['translations'][lang].pop('main_image', None)
        
        structured_articles.append(structured_article)
    
    return structured_articles

@app.route('/news', methods=['GET'])
def get_news():
    """
    Get processed news articles
    Optional parameters:
    - language: Filter by language code (default: all)
    - limit: Maximum number of articles to return (default: all)
    - offset: Start index for pagination (default: 0)
    - refresh: Whether to refresh language summary data (default: false)
    """
    # Get parameters
    language = request.args.get('language')
    limit = request.args.get('limit')
    offset = request.args.get('offset', 0, type=int)
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    # Check if articles are available
    if not article_cache["articles"]:
        try:
            # Try to load from file
            latest_file = "output/latest_articles.json"
            if os.path.exists(latest_file):
                with open(latest_file, 'r', encoding='utf-8') as f:
                    article_cache["articles"] = json.load(f)
                    article_cache["last_updated"] = datetime.fromtimestamp(
                        os.path.getmtime(latest_file)
                    ).isoformat()
        except Exception as e:
            logger.error(f"Error loading articles from file: {e}")
    
    # Check again after attempting to load
    if not article_cache["articles"]:
        # Create language data from supported languages
        available_languages = {}
        for lang_code, lang_info in INDIAN_LANGUAGES.items():
            available_languages[lang_code] = {
                "name": lang_info["name"],
                "tts_supported": True if lang_info.get("tts_code") else False,
                "article_count": 0,
                "article_ids": []
            }
            
        return jsonify({
            "status": "no_data",
            "message": "No news available",
            "count": 0,
            "articles": [],
            "last_updated": None,
            "processing": article_cache["processing"],
            "available_languages": available_languages
        }), 200
    
    # Filter by language if specified
    articles = article_cache["articles"]
    if language and language != 'en':
        articles = [
            article for article in articles 
            if 'translations' in article and language in article['translations']
        ]
    
    # Apply pagination
    if limit:
        try:
            limit = int(limit)
            articles = articles[offset:offset+limit]
        except ValueError:
            pass
    else:
        articles = articles[offset:]
    
    # Structure the articles in the requested format
    structured_articles = get_structured_articles(articles, language)
    
    # Update the article translations organization if requested
    translations_summary = {}
    if refresh:
        translations_summary = organize_translations_by_article_id()
    else:
        # Try to load the summary from file
        translations_summary_file = os.path.join("output", "translations", "languages.json")
        if os.path.exists(translations_summary_file):
            try:
                with open(translations_summary_file, 'r', encoding='utf-8') as f:
                    translations_summary = json.load(f)
            except Exception as e:
                logger.error(f"Error loading languages summary: {e}")
                translations_summary = organize_translations_by_article_id()
        else:
            translations_summary = organize_translations_by_article_id()
    
    return jsonify({
        "status": "success",
        "count": len(structured_articles),
        "last_updated": article_cache["last_updated"],
        "processing": article_cache["processing"],
        "articles": structured_articles,
        "available_languages": translations_summary
    })

@app.route('/status', methods=['GET'])
def get_status():
    """Get the current status of the API and extraction process"""
    return jsonify({
        "status": "success",
        "processing": article_cache["processing"],
        "article_count": len(article_cache["articles"]),
        "last_updated": article_cache["last_updated"],
        "available_languages": list(INDIAN_LANGUAGES.keys())
    })

@app.route('/test', methods=['GET'])
def test():
    """Simple endpoint to check if the API is up and running"""
    return jsonify({
        "status": "success",
        "message": "API is up and running"
    }), 200

@app.route('/languages', methods=['GET'])
def get_languages():
    """Get available languages and their translation status"""
    # Generate fresh language data
    languages_data = organize_translations_by_article_id()
    
    # If no data is found, try to read from file
    if not languages_data:
        translations_summary_file = os.path.join("output", "translations", "languages.json")
        if os.path.exists(translations_summary_file):
            try:
                with open(translations_summary_file, 'r', encoding='utf-8') as f:
                    languages_data = json.load(f)
            except Exception as e:
                logger.error(f"Error loading languages data: {e}")
    
    # If still no data, create default from supported languages
    if not languages_data:
        languages_data = {}
        for lang_code, lang_info in INDIAN_LANGUAGES.items():
            languages_data[lang_code] = {
                "name": lang_info["name"],
                "tts_supported": True if lang_info.get("tts_code") else False,
                "article_count": 0
            }
    
    return jsonify({
        "status": "success",
        "languages": languages_data
    })

@app.route('/article/<article_id>', methods=['GET'])
def get_article(article_id):
    """Get a specific article with all its translations
    
    Args:
        article_id: The unique ID of the article to retrieve
    """
    # Check if articles are available in cache
    if not article_cache["articles"]:
        try:
            # Try to load from file
            latest_file = "output/latest_articles.json"
            if os.path.exists(latest_file):
                with open(latest_file, 'r', encoding='utf-8') as f:
                    article_cache["articles"] = json.load(f)
                    article_cache["last_updated"] = datetime.fromtimestamp(
                        os.path.getmtime(latest_file)
                    ).isoformat()
        except Exception as e:
            logger.error(f"Error loading articles from file: {e}")
    
    # Find the requested article
    article = next((a for a in article_cache["articles"] if a.get('article_id') == article_id), None)
    
    if not article:
        return jsonify({
            "status": "not_found",
            "message": f"Article with ID {article_id} not found"
        }), 404
    
    # Structure the article data
    structured_articles = get_structured_articles([article])
    
    # Get translation metadata
    article_translations_dir = os.path.join("output", "translations", "articles", article_id)
    translations_metadata = {}
    
    if os.path.exists(article_translations_dir):
        for lang_dir in os.listdir(article_translations_dir):
            lang_path = os.path.join(article_translations_dir, lang_dir)
            if os.path.isdir(lang_path):
                metadata_file = os.path.join(lang_path, "voice_metadata.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            translations_metadata[lang_dir] = json.load(f)
                    except Exception as e:
                        logger.error(f"Error loading metadata for article {article_id}, language {lang_dir}: {e}")
    
    return jsonify({
        "status": "success",
        "article": structured_articles[0] if structured_articles else None,
        "translations_metadata": translations_metadata
    })

@app.route('/images/<filename>')
def serve_image(filename):
    """Serve images from the output/images directory"""
    return send_from_directory('output/images', filename)

if __name__ == '__main__':
    # Ensure output directories exist
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/images", exist_ok=True)
    os.makedirs("output/translations", exist_ok=True)
    os.makedirs("output/translations/articles", exist_ok=True)
    
    # Start the server
    # port = os.getenv('PORT', 5000)
    port = int(os.getenv('PORT', 5000))  # fallback to 5000 for local dev
    app.run(host='0.0.0.0', port=port, debug=True)