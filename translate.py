from google.cloud import translate_v2 as translate
from google.cloud import texttospeech
from google.oauth2 import service_account
import os
import json
import sys
import glob
import hashlib
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Configure more detailed logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("translate")

# Load environment variables
load_dotenv()

# Set up TTS credentials

credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if os.path.exists(credentials_path):
    tts_credentials = service_account.Credentials.from_service_account_file(credentials_path)
    logger.info(f"Loaded TTS credentials from {credentials_path}")
else:
    logger.warning(f"Warning: TTS credentials file not found at  {credentials_path}")
    tts_credentials = None

# Initialize the Google Translate client
translate_client = translate.Client()
logger.info("Initialized Google Translate client")

# Indian languages supported by Google Translate with their TTS language codes
target_languages = {
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
}

logger.info(f"Supported languages: {', '.join(target_languages.keys())}")

def generate_voice_file(article_data, lang_code):
    """Generate a voice file for the translated article summary and return the file path."""
    # Ensure article has an ID
    if 'article_id' in article_data:
        article_id = article_data['article_id']
    elif 'url' in article_data:
        article_id = hashlib.md5(article_data.get('url', '').encode()).hexdigest()[:10]
    else:
        # Generate a random ID if neither is available
        article_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:10]
        
    headline = article_data.get('headline', 'Unknown Title')[:30]
    
    if not tts_credentials:
        logger.warning(f"Skipping voice generation for article {article_id} ({headline}): No credentials available")
        return None
        
    try:
        # Get the summary text - try multiple fields if summary is not available
        summary = article_data.get('summary', '')
        
        # If summary is empty, try content field
        if not summary and 'content' in article_data:
            logger.warning(f"No summary found for article {article_id}, using content instead")
            content = article_data.get('content', '')
            # Limit content to first 1000 characters if it exists
            summary = content[:1000] if content else ''
            
        # If still no content, use headline as fallback
        if not summary:
            logger.warning(f"No content found for article {article_id}, using headline as fallback")
            summary = f"Article titled: {headline}"
            
        # Final check - if we still don't have anything to speak, skip this article
        if not summary or len(summary.strip()) < 10:  # Require at least 10 chars of text
            logger.warning(f"Skipping voice generation for article {article_id} ({headline}): Insufficient text content")
            return None
            
        # Check if language is supported for TTS
        if lang_code not in target_languages:
            logger.warning(f"Skipping voice generation for article {article_id} ({headline}): Language {lang_code} not supported")
            return None
            
        # Get the TTS language code
        tts_language_code = target_languages[lang_code]['tts_code']
        
        # Create TTS client
        client = texttospeech.TextToSpeechClient(credentials=tts_credentials)
        
        # Get the voice name - Chirp3 HD or Kore voices are high quality
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
        
        logger.info(f"Generating speech for article {article_id} ({headline})")
        
        # Try with specific voice, with fallback options
        try:
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            logger.info(f"Successfully generated speech with voice {voice_name}")
        except Exception as e:
            logger.warning(f"Error with specific voice {voice_name}, trying generic voice: {e}")
            try:
                # Fallback to generic voice selection
                voice = texttospeech.VoiceSelectionParams(
                    language_code=tts_language_code
                )
                response = client.synthesize_speech(
                    input=synthesis_input,
                    voice=voice,
                    audio_config=audio_config
                )
                logger.info(f"Successfully generated speech with generic voice for {tts_language_code}")
            except Exception as e2:
                logger.error(f"Error generating speech with generic voice: {e2}")
                # Last resort: try English voice if this isn't already English
                if tts_language_code != 'en-IN':
                    try:
                        logger.warning(f"Trying English voice as last resort for {article_id}")
                        voice = texttospeech.VoiceSelectionParams(
                            language_code='en-IN'
                        )
                        response = client.synthesize_speech(
                            input=synthesis_input,
                            voice=voice,
                            audio_config=audio_config
                        )
                        logger.info(f"Successfully generated speech with English fallback voice")
                    except Exception as e3:
                        logger.error(f"All voice generation attempts failed for {article_id}: {e3}")
                        return None
                else:
                    return None
        
        # Create output directory for translations
        voice_dir = os.path.join("output", "translations", lang_code, "voice")
        os.makedirs(voice_dir, exist_ok=True)
        
        # Include language code in filename for clarity
        filename_prefix = f"{lang_code}_{article_id}"
        
        # Create a safe filename from the headline
        safe_text = "".join(c if c.isalnum() or c in " _-" else "_" for c in headline)
        safe_text = safe_text.strip().replace(" ", "_")
        
        # Create output path
        output_file = os.path.join(voice_dir, f"{filename_prefix}_{safe_text}.mp3")
        
        # Write the audio content
        try:
            with open(output_file, "wb") as out:
                out.write(response.audio_content)
            
            logger.info(f"Audio content written to '{output_file}'")
            
            # Return the relative path for storage in JSON
            return os.path.relpath(output_file)
        except Exception as e:
            logger.error(f"Error writing audio file {output_file}: {e}")
            # Try to write to a simpler filename as fallback
            try:
                simple_output_file = os.path.join(voice_dir, f"{filename_prefix}.mp3")
                with open(simple_output_file, "wb") as out:
                    out.write(response.audio_content)
                logger.info(f"Audio content written to simplified path '{simple_output_file}'")
                return os.path.relpath(simple_output_file)
            except Exception as e2:
                logger.error(f"Failed to write audio file even with simplified path: {e2}")
                return None
    except Exception as e:
        logger.error(f"Error generating voice file for article {article_id} ({headline}): {e}")
        return None

def get_latest_articles_file():
    """Find the latest articles JSON file in the output directory"""
    # First check for the fixed latest_articles.json file
    fixed_path = os.path.join("output", "latest_articles.json")
    if os.path.exists(fixed_path):
        logger.info(f"Found latest articles file: {fixed_path}")
        return fixed_path
        
    # Then look for time-stamped files
    files = glob.glob("output/latest_articles_*.json")
    if not files:
        raise FileNotFoundError("No latest_articles JSON files found in output directory")
    
    # Sort by modification time (newest first)
    latest_file = max(files, key=os.path.getmtime)
    logger.info(f"Found latest articles file: {latest_file}")
    return latest_file

def translate_article(article, lang_code):
    """Translate specific fields of an article"""
    # Make a copy of the article to preserve original structure
    translated_article = article.copy()
    article_id = hashlib.md5(article.get('url', '').encode()).hexdigest()[:10]
    headline = article.get('headline', '')[:30]
    
    # Fields to translate
    fields = ["headline", "summary", "author", "source", "category"]
    
    # Translate each field if it exists
    for field in fields:
        if field in article and article[field]:
            try:
                logger.info(f"Translating {field} for article {article_id} ({headline})")
                
                # Rate limiting to avoid quota issues (2 requests per second)
                time.sleep(0.5)
                
                # Retry mechanism for translation
                max_retries = 3
                retry_delay = 2
                
                for retry in range(max_retries):
                    try:
                        translated_article[field] = translate_client.translate(
                            article[field], target_language=lang_code
                        )["translatedText"]
                        logger.info(f"Successfully translated {field}")
                        break
                    except Exception as e:
                        if retry < max_retries - 1:
                            logger.warning(f"Translation attempt {retry+1} failed, retrying in {retry_delay} seconds: {e}")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"Error translating {field} after {max_retries} attempts: {e}")
                            raise
            except Exception as e:
                logger.error(f"Error translating {field} for article {article_id} ({headline}): {e}")
                # Use original text if translation fails
                translated_article[field] = article[field]
    
    # Handle tags separately (they're a list)
    if "tags" in article and article["tags"]:
        translated_tags = []
        logger.info(f"Translating {len(article['tags'])} tags for article {article_id} ({headline})")
        for tag in article["tags"]:
            try:
                # Rate limiting to avoid quota issues (5 tags per second)
                time.sleep(0.2)
                
                translated_tag = translate_client.translate(
                    tag, target_language=lang_code
                )["translatedText"]
                translated_tags.append(translated_tag)
            except Exception as e:
                logger.error(f"Error translating tag '{tag}' for article {article_id} ({headline}): {e}")
                translated_tags.append(tag)  # Keep original if translation fails
        
        translated_article["tags"] = translated_tags
        logger.info(f"Successfully translated {len(translated_tags)} tags")
    
    # Add translation metadata
    translated_article["translated"] = True
    translated_article["translated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    translated_article["language"] = lang_code
    
    return translated_article

def get_previously_translated_articles(lang_code):
    """
    Get a set of article IDs that have already been translated to the specified language.
    
    Args:
        lang_code: Language code to check for previous translations
        
    Returns:
        Set of article IDs that have already been translated
    """
    translated_ids = set()
    
    # Check if translations directory exists
    translation_dir = os.path.join("output", "translations", lang_code)
    if not os.path.exists(translation_dir):
        logger.info(f"No previous translations found for {lang_code}")
        return translated_ids
    
    # Find all translation files for this language
    translation_files = glob.glob(f"{translation_dir}/articles_{lang_code}_*.json")
    if not translation_files:
        logger.info(f"No translation files found for {lang_code}")
        return translated_ids
    
    # Process each translation file
    for file_path in translation_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                translated_articles = json.load(f)
                
                # Extract article IDs
                for article in translated_articles:
                    if 'article_id' in article:
                        translated_ids.add(article['article_id'])
                    elif 'url' in article:
                        # Generate ID from URL if article_id not present
                        article_id = hashlib.md5(article['url'].encode()).hexdigest()[:10]
                        translated_ids.add(article_id)
                
            logger.info(f"Found {len(translated_ids)} previously translated articles in {file_path}")
        except Exception as e:
            logger.error(f"Error reading translation file {file_path}: {e}")
    
    return translated_ids

def process_all_languages(articles, selected_languages=None):
    """
    Process all supported languages or selected languages.
    
    Args:
        articles: List of articles to translate
        selected_languages: List of language codes to process (if None, all languages)
    
    Returns:
        Dictionary of language codes mapped to output files
    """
    result_files = {}
    voice_generation_stats = {}
    
    # Determine which languages to process
    languages_to_process = selected_languages if selected_languages else target_languages.keys()
    logger.info(f"Processing {len(languages_to_process)} languages: {', '.join(languages_to_process)}")
    
    for lang_code in languages_to_process:
        if lang_code not in target_languages:
            logger.warning(f"Skipping unsupported language: {lang_code}")
            continue
            
        logger.info(f"Starting processing for language: {lang_code} ({target_languages[lang_code]['name']})")
        
        # Get previously translated articles
        previously_translated = get_previously_translated_articles(lang_code)
        logger.info(f"Found {len(previously_translated)} previously translated articles for {lang_code}")
        
        # Create output directories
        os.makedirs("output/translations", exist_ok=True)
        os.makedirs(f"output/translations/{lang_code}", exist_ok=True)
        os.makedirs(f"output/translations/{lang_code}/voice", exist_ok=True)
        
        # Filter articles that need translation
        articles_to_translate = []
        for article in articles:
            # Generate article ID if not present
            if 'article_id' not in article:
                article_id = hashlib.md5(article.get('url', '').encode()).hexdigest()[:10]
            else:
                article_id = article['article_id']
                
            # Check if article has already been translated
            if article_id in previously_translated:
                logger.info(f"Skipping article {article_id} ({article.get('headline', '')[:30]}) - already translated")
                continue
                
            articles_to_translate.append(article)
        
        # Check if there are any new articles to translate
        if not articles_to_translate:
            logger.info(f"No new articles to translate for {lang_code}")
            continue
            
        logger.info(f"Found {len(articles_to_translate)} new articles to translate for {lang_code}")
        
        # Translate articles and generate voice files
        translated_articles = []
        start_time = time.time()
        voice_success_count = 0
        voice_failure_count = 0
        
        for i, article in enumerate(articles_to_translate):
            logger.info(f"Processing article {i+1}/{len(articles_to_translate)} for {lang_code}")
            
            # Translate the article
            translated_article = translate_article(article, lang_code)
            
            # Generate voice file for the translated summary
            voice_file = generate_voice_file(translated_article, lang_code)
            if voice_file:
                translated_article['voice_file'] = voice_file
                voice_success_count += 1
            else:
                voice_failure_count += 1
                logger.warning(f"Failed to generate voice file for article {i+1}/{len(articles_to_translate)}")
            
            translated_articles.append(translated_article)
            
            # Log progress periodically
            if (i+1) % 5 == 0:
                elapsed = time.time() - start_time
                avg_time = elapsed / (i+1)
                remaining = avg_time * (len(articles_to_translate) - (i+1))
                logger.info(f"Progress: {i+1}/{len(articles_to_translate)} articles processed for {lang_code}")
                logger.info(f"Elapsed time: {elapsed:.1f}s, Avg per article: {avg_time:.1f}s")
                logger.info(f"Estimated remaining time: {remaining:.1f}s ({remaining/60:.1f}min)")
        
        # Save voice generation statistics
        voice_generation_stats[lang_code] = {
            "total_articles": len(articles_to_translate),
            "voice_success": voice_success_count,
            "voice_failure": voice_failure_count,
            "success_rate": f"{(voice_success_count / len(articles_to_translate) * 100):.1f}%" if articles_to_translate else "N/A"
        }
        
        # Only save if there are translated articles
        if translated_articles:
            # Save translated articles
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"output/translations/{lang_code}/articles_{lang_code}_{timestamp}.json"
            
            with open(output_file, "w", encoding="utf-8") as file:
                json.dump(translated_articles, file, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved {len(translated_articles)} translated articles to {output_file}")
            logger.info(f"Voice generation: {voice_success_count} successful, {voice_failure_count} failed")
            result_files[lang_code] = output_file
            
            # Total processing time
            total_time = time.time() - start_time
            logger.info(f"Finished processing {lang_code} in {total_time:.1f}s ({total_time/60:.1f}min)")
        else:
            logger.info(f"No new articles translated for {lang_code}")
    
    # Log voice generation statistics
    if voice_generation_stats:
        logger.info("\n=== VOICE GENERATION STATISTICS ===")
        for lang, stats in voice_generation_stats.items():
            logger.info(f"{lang} ({target_languages[lang]['name']}): {stats['voice_success']}/{stats['total_articles']} successful ({stats['success_rate']})")
    
    return result_files

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Translate articles to Indian languages')
    parser.add_argument('languages', help='Language codes to translate to (comma-separated) or "all" for all languages')
    parser.add_argument('--max', '-m', type=int, help='Maximum number of articles to translate', default=None)
    args = parser.parse_args()
    
    # Parse language input
    lang_input = args.languages.strip().lower()
    
    # Find latest articles file
    try:
        input_file = get_latest_articles_file()
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    
    # Read latest articles file
    try:
        with open(input_file, "r", encoding="utf-8") as file:
            articles = json.load(file)
        logger.info(f"Loaded {len(articles)} articles from {input_file}")
        
        # Limit articles if max is specified
        if args.max and args.max > 0 and args.max < len(articles):
            logger.info(f"Limiting to {args.max} articles as specified by --max parameter")
            articles = articles[:args.max]
    except Exception as e:
        logger.error(f"Error reading {input_file}: {e}")
        sys.exit(1)
    
    # Process articles based on language input
    if lang_input == "all":
        # Process all supported languages
        logger.info("Processing ALL supported languages")
        result_files = process_all_languages(articles)
    else:
        # Process specific languages
        languages = [lang.strip() for lang in lang_input.split(",") if lang.strip()]
        logger.info(f"Processing specified languages: {', '.join(languages)}")
        result_files = process_all_languages(articles, languages)
    
    # Print summary of results
    logger.info("\n=== TRANSLATION SUMMARY ===")
    logger.info(f"Total articles processed: {len(articles)}")
    logger.info(f"Total languages processed: {len(result_files)}")
    for lang, file in result_files.items():
        logger.info(f"  - {lang}: {file}")
    logger.info("=== TRANSLATION COMPLETE ===")

if __name__ == "__main__":
    main()