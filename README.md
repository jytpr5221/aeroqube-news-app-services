# Latest News Extractor and API

A tool to extract, summarize, translate, and vocalize the latest news articles from The Hindu website. It cleans up content, removes common markers and boilerplate text, generates concise summaries, and provides translations with text-to-speech capabilities.

## Features

- Extracts latest news articles from The Hindu website
- Cleans content by removing navigation elements, publication markers, and other non-article content
- Handles potential paywall content by using alternate extraction methods
- Generates concise summaries of articles
- Translates articles into multiple Indian languages
- Converts summaries to speech using Google Text-to-Speech
- Uploads audio files to Appwrite storage
- Provides a RESTful API to access all functionality

## API Endpoints

### GET `/status`
Check the status of the API and extraction process.

**Response:**
```json
{
  "status": "success",
  "processing": false,
  "article_count": 10,
  "last_updated": "2023-04-05T12:34:56",
  "available_languages": ["en", "hi", "ta", ...]
}
```

### POST `/extract`
Extract news articles, summarize, translate, and generate TTS.

**Query Parameters:**
- `languages`: Comma-separated list of language codes to translate to (default: all)
- `background`: If 'true', run in background thread (default: 'true')

**Example:**
```
POST /extract?languages=hi,ta,te&background=true
```

**Response:**
```json
{
  "status": "processing",
  "message": "News extraction started in background",
  "languages": "hi,ta,te"
}
```

### GET `/news`
Get processed news articles with their translations and TTS audio URLs.

**Query Parameters:**
- `language`: Filter by language code (default: all)
- `limit`: Maximum number of articles to return (default: all)
- `offset`: Start index for pagination (default: 0)

**Example:**
```
GET /news?language=hi&limit=5&offset=0
```

**Response:**
```json
{
  "status": "success",
  "count": 5,
  "last_updated": "2023-04-05T12:34:56",
  "processing": false,
  "articles": [...]
}
```

## Files

- `latest_extractor.py`: Core functionality for extracting and cleaning articles
- `translate.py`: Translates articles to multiple Indian languages
- `news_pipeline.py`: Script that combines extraction, summarization, and translation
- `api.py`: Flask API to expose the functionality via HTTP endpoints
- `.env`: Configuration file for API keys and service credentials
- `output/`: Folder where extracted articles, summaries, and translations are saved

## Usage

### Running the API

Start the Flask API server:

```bash
python api.py
```

The server will run on `http://0.0.0.0:5000` by default.

### Command Line Usage

You can also run the full extraction and summarization pipeline directly:

```bash
python news_pipeline.py
```

Or use the extractor module directly:

```bash
python latest_extractor.py
```

## Environment Variables

Create a `.env` file with the following variables:

```
GOOGLE_APPLICATION_CREDENTIALS=path/to/google-credentials.json
APPWRITE_PROJECT_ID=your_project_id
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_STORAGE_ID=your_storage_id
APPWRITE_AUDIO_BUCKET_ID=your_bucket_id
APPWRITE_AUDIO_BUCKET_NAME=News_TTS
APPWRITE_API_KEY=your_api_key
```

## Requirements

See requirements.txt for dependencies. Install with:

```bash
pip install -r requirements.txt
```

## Output Files

The system generates the following output files in the `output/` directory:

- `latest_articles.json`: Latest extracted articles (fixed filename)
- `latest_articles_{timestamp}.json`: Timestamped JSON file containing extracted articles
- `processed_articles_{timestamp}.json`: Timestamped JSON file containing processed articles with translations
- `translations/{lang_code}/articles_{lang_code}_{timestamp}.json`: Translated articles for each language
- `translations/{lang_code}/voice/{lang_code}_{article_id}.mp3`: TTS audio files for each language 