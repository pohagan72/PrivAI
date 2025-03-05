# Domain Verifier: Legal Domain Analyzer

A tool that analyzes domains to determine if they primarily operate in the legal field. It uses web scraping, natural language processing, and the Ollama language model to classify websites.

![Domain Verifier Screenshot](https://github.com/user-attachments/assets/27603127-88d0-4c3c-8370-7fa513224e16)

## Features

- Upload CSV or Excel files containing domain lists
- Automatically extracts and analyzes website content
- Classifies domains as legal or non-legal using LLM analysis
- Processes multiple domains concurrently for better performance
- Provides real-time progress tracking
- Generates downloadable results in CSV format

## Requirements

- Python 3.6+
- Ollama (https://ollama.com/)
- Chrome Browser

## Installation

1. Clone the repository:
   ```bash
   git clone <repository_url>
   cd <repository_directory>
   ```

2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Linux/macOS
   venv\Scripts\activate  # On Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Start Ollama:
   ```bash
   ollama serve
   ```

2. Run the application:
   ```bash
   python main.py
   ```

3. Open your browser and navigate to `http://127.0.0.1:5000/`

4. Upload your file containing domains and click "Start Analysis"

5. Monitor the progress and download results when complete

## How It Works

The tool:
1. Extracts text from each website using requests or Selenium
2. Analyzes the content using the Ollama LLama3 model
3. Classifies each domain as "yes" (legal), "no" (non-legal), or "unsure"
4. Generates a CSV with the results
