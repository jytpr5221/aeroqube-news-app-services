#!/usr/bin/env python
import os
import sys
import glob
import time
import json
import logging
import subprocess
import argparse
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("news_pipeline")

# All supported languages for translation with their names
ALL_LANGUAGES = {
    'as': 'Assamese',
    'bn': 'Bengali',
    'bho': 'Bhojpuri',
    'gu': 'Gujarati',
    'hi': 'Hindi',
    'kn': 'Kannada',
    'kok': 'Konkani',
    'mai': 'Maithili',
    'ml': 'Malayalam',
    'mni-Mtei': 'Manipuri',
    'mr': 'Marathi',
    'or': 'Odia',
    'pa': 'Punjabi',
    'sa': 'Sanskrit',
    'sd': 'Sindhi',
    'ta': 'Tamil',
    'te': 'Telugu',
    'ur': 'Urdu',
}

def run_command(command, timeout=None):
    """Run a command and return its output with optional timeout"""
    logger.info(f"Running command: {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=timeout
        )
        logger.info(f"Command completed with exit code {result.returncode}")
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exit code {e.returncode}")
        logger.error(f"Error output: {e.stderr}")
        return False, e.stderr
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out after {timeout} seconds")
        return False, f"Timeout after {timeout} seconds"

def get_latest_articles_file():
    """Find the latest articles JSON file in the output directory"""
    # First check for the fixed latest_articles.json file
    fixed_path = "output/latest_articles.json"
    if os.path.exists(fixed_path):
        logger.info(f"Found latest articles file: {fixed_path}")
        return fixed_path
    
    # If not found, look for timestamped files
    files = glob.glob("output/latest_articles_*.json")
    if not files:
        logger.error("No latest_articles JSON files found in output directory")
        return None
    
    # Sort by modification time (newest first)
    latest_file = max(files, key=os.path.getmtime)
    logger.info(f"Found latest articles file: {latest_file}")
    return latest_file

def extract_latest_articles():
    """Run latest_extractor.py to extract the latest articles"""
    logger.info("Extracting latest articles...")
    
    # Run the latest_extractor.py script
    success, output = run_command(["python", "latest_extractor.py"], timeout=300)  # 5 minute timeout
    
    if not success:
        logger.error("Failed to extract latest articles")
        return None
    
    # Get the latest articles file
    latest_file = get_latest_articles_file()
    
    if not latest_file:
        logger.error("Could not find the latest articles file after extraction")
        return None
    
    # Check if the file contains valid JSON and has articles
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            articles = json.load(f)
        
        if not articles:
            logger.error("No articles found in the latest articles file")
            return None
            
        logger.info(f"Successfully extracted {len(articles)} articles")
        return latest_file
    except Exception as e:
        logger.error(f"Error reading articles file: {e}")
        return None

def translate_articles(latest_file, languages=None, max_articles=None):
    """
    Translate the articles to selected languages
    
    Args:
        latest_file: Path to the latest articles file
        languages: List of language codes to translate to (None for all)
        max_articles: Maximum number of articles to translate (None for all)
    """
    # Determine which languages to process
    if languages:
        language_codes = languages.split(',')
        languages_str = ", ".join([f"{code} ({ALL_LANGUAGES.get(code, 'Unknown')})" for code in language_codes])
        logger.info(f"Translating articles to selected languages: {languages_str}")
    else:
        language_codes = list(ALL_LANGUAGES.keys())
        logger.info(f"Translating articles to ALL supported languages ({len(language_codes)} languages)")
    
    # Prepare command
    translate_cmd = ["python", "translate.py"]
    
    # Add languages parameter
    if languages:
        translate_cmd.append(languages)
    else:
        translate_cmd.append("all")
        
    # Add max_articles parameter if specified
    if max_articles:
        translate_cmd.extend(["--max", str(max_articles)])
    
    translated_files = []
    start_time = time.time()
    
    # Run translate.py with selected parameters
    logger.info(f"Starting translation process with command: {' '.join(translate_cmd)}")
    success, output = run_command(translate_cmd, timeout=3600)  # 1 hour timeout
    
    if success:
        # Find all translation files
        for lang in language_codes:
            lang_files = glob.glob(f"output/translations/{lang}/articles_{lang}_*.json")
            if lang_files:
                translated_file = max(lang_files, key=os.path.getmtime)
                logger.info(f"Translation to {lang} ({ALL_LANGUAGES.get(lang, 'Unknown')}) saved to {translated_file}")
                translated_files.append(translated_file)
            else:
                logger.warning(f"Could not find translated file for language {lang} ({ALL_LANGUAGES.get(lang, 'Unknown')})")
    else:
        logger.error("Translation process failed")
    
    # Calculate total time
    total_time = time.time() - start_time
    logger.info(f"Translation process completed in {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
    
    return translated_files

def create_translation_summary(latest_file, translated_files):
    """Create a summary of the translation process"""
    summary = {
        "original_file": latest_file,
        "timestamp": datetime.now().isoformat(),
        "languages_processed": len(translated_files),
        "translations": []
    }
    
    # Get original article count
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            articles = json.load(f)
            summary["original_article_count"] = len(articles)
    except Exception as e:
        logger.error(f"Error reading original articles: {e}")
        summary["original_article_count"] = 0
    
    # Get information about each translation
    for file_path in translated_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Extract language code from filename
                lang_code = os.path.basename(file_path).split('_')[1]
                
                # Count articles with voice files
                voice_count = sum(1 for article in data if 'voice_file' in article)
                
                translation_info = {
                    "language_code": lang_code,
                    "language_name": ALL_LANGUAGES.get(lang_code, "Unknown"),
                    "file_path": file_path,
                    "article_count": len(data),
                    "voice_files_count": voice_count
                }
                
                summary["translations"].append(translation_info)
        except Exception as e:
            logger.error(f"Error processing translation file {file_path}: {e}")
    
    # Save summary
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_file = f"output/translation_summary_{timestamp}.json"
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Translation summary saved to {summary_file}")
    return summary_file

def main():
    """Main function to run the complete news pipeline"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="News Pipeline: Extract and translate articles")
    parser.add_argument("--languages", "-l", type=str, help="Comma-separated list of language codes (default: all languages)", default=None)
    parser.add_argument("--max", "-m", type=int, help="Maximum number of articles to translate (default: all)", default=None)
    parser.add_argument("--skip-extract", "-s", action="store_true", help="Skip article extraction step")
    args = parser.parse_args()
    
    logger.info("=== STARTING NEWS PIPELINE ===")
    
    # Log pipeline configuration
    if args.languages:
        logger.info(f"Translation languages: {args.languages}")
    else:
        logger.info(f"Translation languages: ALL ({len(ALL_LANGUAGES)} languages)")
        
    if args.max:
        logger.info(f"Maximum articles to translate: {args.max}")
    else:
        logger.info("Maximum articles to translate: ALL")
        
    if args.skip_extract:
        logger.info("Skipping article extraction step")
    
    # Step 1: Extract latest articles (unless skipped)
    latest_file = None
    if not args.skip_extract:
        logger.info("STEP 1: Extracting latest articles")
        latest_file = extract_latest_articles()
        if not latest_file:
            logger.error("Article extraction failed. Aborting pipeline.")
            return 1
    else:
        logger.info("STEP 1: Skipping article extraction")
        latest_file = get_latest_articles_file()
        if not latest_file:
            logger.error("No latest articles file found. Cannot proceed with translation.")
            return 1
        
    # Step 2: Translate to specified languages
    logger.info("STEP 2: Translating articles")
    translated_files = translate_articles(latest_file, args.languages, args.max)
    
    if not translated_files:
        logger.error("No translations were generated. Aborting pipeline.")
        return 1
    
    # Step 3: Create summary
    logger.info("STEP 3: Creating translation summary")
    summary_file = create_translation_summary(latest_file, translated_files)
    
    # Report results
    logger.info("=== PIPELINE COMPLETED SUCCESSFULLY ===")
    logger.info(f"Original articles: {latest_file}")
    logger.info(f"Translated to {len(translated_files)} languages")
    logger.info(f"Summary: {summary_file}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 