from flask import Flask, render_template, request, send_file, jsonify
import pandas as pd
import requests
import ollama
import io
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import tldextract
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import WebDriverException, TimeoutException

app = Flask(__name__)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit
app.config['TIMEOUT'] = 15  # Timeout for browser operations
app.config['WORKERS'] = 10  # Number of worker threads for processing

# Global variables for progress tracking and job result storage
progress_lock = threading.Lock()
progress = {
    'total': 0,
    'completed': 0,
    'processing': False,
    'error': None
}
# This will hold the CSV result once processing is finished.
job_result_buffer = None

# Prompt for Ollama
prompt = """
You are a seasoned legal expert with comprehensive knowledge of the legal field, encompassing legal practice (litigation, transactional, advisory, etc.), legal technology (software, platforms, etc. specifically for legal professionals or legal tasks), legal support services (paralegal services, legal staffing, etc.), legal education, and legal publishing.

Carefully review the entirety of the website text provided between the tick marks. Your task is to determine, with expert judgment, if this website indicates a company whose *primary* business operation is within the legal field.

- **Legal Terminology**: Look for specific legal terms (e.g., "litigation," "contract," "compliance").
- **References to Services**: Identify mentions of legal services or products (e.g., "legal advice," "consultation," "representation").
- **Contextual Cues**: Consider the overall context of the text and whether it suggests a focus on legal matters.

I want only a one-word response generated based on your expert opinion.

- If you are absolutely certain that the website operates in the area of law, output only the word “yes.”
- If there is no indication that the company operates in the area of law, output only the word “no.”
- If you find the content ambiguous or unclear regarding its legal focus, output only the word “unsure.”
"""

def check_ollama_running():
    try:
        ollama.pull("llama3:8b")
        return True
    except Exception as e:
        print(f"Ollama check failed: {e}")
        return False

def start_ollama():
    try:
        subprocess.Popen(['ollama', 'serve'])
        return True
    except Exception as e:
        print(f"Failed to start Ollama: {e}")
        return False

def fetch_with_selenium(url):
    """Fetches content from a URL using Selenium and extracts text."""
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(app.config['TIMEOUT'])
        driver.get(url)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return ' '.join(soup.stripped_strings)
    except TimeoutException as e:
        print(f"Selenium Timeout error for {url}: {e}")
        return f"Browser Timeout Error: {e}"
    except WebDriverException as e:
        print(f"Selenium WebDriver error for {url}: {e}")
        return f"Browser Driver Error: {e}"
    except Exception as e:
        print(f"Selenium general error for {url}: {e}")
        return f"Browser Error: {e}"
    finally:
        if driver:
            driver.quit()

def fetch_and_extract_text(url):
    """Fetches content from a URL and extracts text, with fallback to Selenium."""
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        try:
            response = requests.get(url, headers=headers, timeout=app.config['TIMEOUT'])
            response.raise_for_status()
            # Basic heuristic: if content hints at heavy JavaScript and is very short, try Selenium.
            if "javascript" in response.text.lower() and len(response.text) < 1000:
                print(f"Trying Selenium for JavaScript content: {url}")
                return fetch_with_selenium(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            return ' '.join(soup.stripped_strings)
        except requests.exceptions.RequestException as e:
            print(f"Requests failed for {url}, trying Selenium: {e}")
            return fetch_with_selenium(url)
    except Exception as e:
        print(f"Error extracting text from {url}: {e}")
        return f"Extraction Error: {e}"

def classify_text(text):
    if not text.strip():
        return "unsure"
    try:
        response = ollama.chat(model='llama3:8b', messages=[
            {'role': 'user', 'content': f"{prompt}\n\n ```{text}```"}
        ])
        return response['message']['content'].strip().lower()
    except Exception as e:
        print(f"Ollama error: {e}")
        return "unsure"

def is_valid_domain(domain):
    """Validates if a domain is well-formed and appears to resolve."""
    try:
        extracted = tldextract.extract(domain)
        if not extracted.domain or not extracted.suffix:
            return False
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.head(f"http://{domain}", headers=headers, timeout=5, allow_redirects=True)
        return response.status_code < 500
    except requests.exceptions.RequestException:
        return False
    except Exception as e:
        print(f"Unexpected error validating domain {domain}: {e}")
        return False

def process_domain(domain, results, idx):
    """Processes a single domain and stores the result."""
    try:
        if not is_valid_domain(domain):
            with progress_lock:
                results[idx] = "invalid domain"
                progress['completed'] += 1
            return

        fetch_url = domain if domain.startswith(('http://', 'https://')) else 'http://' + domain
        text = fetch_and_extract_text(fetch_url)
        if text.startswith("Request Error:") or text.startswith("Extraction Error:") or text.startswith("Browser"):
            with progress_lock:
                results[idx] = text
                progress['completed'] += 1
            return

        result = classify_text(text)
        with progress_lock:
            results[idx] = result
            progress['completed'] += 1
    except Exception as e:
        print(f"Error processing {domain}: {e}")
        with progress_lock:
            results[idx] = f"Processing Error: {e}"
            progress['error'] = str(e)
            progress['completed'] += 1

def background_process(domains):
    """Background thread function to process domains using a ThreadPoolExecutor."""
    global job_result_buffer
    total = len(domains)
    results = [None] * total
    # Check and (if needed) start Ollama before processing
    if not check_ollama_running():
        if not start_ollama():
            with progress_lock:
                progress['processing'] = False
                progress['error'] = "Ollama is not running and could not be started. Please ensure Ollama is installed and running."
            return

    with ThreadPoolExecutor(max_workers=app.config['WORKERS']) as executor:
        for idx, domain in enumerate(domains):
            executor.submit(process_domain, domain, results, idx)
        # The with block waits until all tasks complete

    # Post-processing: standardize the classification output.
    final_results = []
    for r in results:
        if r not in ['yes', 'no', 'unsure']:
            final_results.append("Error")
        else:
            final_results.append(r)
    
    # Create CSV in memory.
    try:
        df = pd.DataFrame({'domain': domains, 'legal_classification': final_results})
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False)
        buffer.seek(0)
        job_result_buffer = buffer
    except Exception as e:
        print(f"Error generating result CSV: {e}")
        with progress_lock:
            progress['error'] = str(e)
    finally:
        with progress_lock:
            progress['processing'] = False

@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            error = 'Please select a valid Excel or CSV file.'
            return render_template('index.html', error=error, progress=progress)
        try:
            if file.filename.endswith('.xlsx'):
                df = pd.read_excel(file)
            else:
                df = pd.read_csv(file)
            
            # Assume domains are in the first column.
            domains = df.iloc[:, 0].astype(str).tolist()
            domains = [d.strip() for d in domains]

            with progress_lock:
                progress['total'] = len(domains)
                progress['completed'] = 0
                progress['processing'] = True
                progress['error'] = None

            # Start background processing so the HTTP request finishes immediately.
            thread = threading.Thread(target=background_process, args=(domains,))
            thread.start()

            # Render a page that will poll for progress.
            return render_template('index.html', message="File uploaded. Processing started.", progress=progress)
        except Exception as e:
            error = f"Processing error: {e}"
            print(f"Error: {e}")
            with progress_lock:
                progress['processing'] = False
                progress['error'] = str(e)
    return render_template('index.html', error=error, progress=progress)

@app.route('/progress')
def get_progress():
    with progress_lock:
        return jsonify(progress)

@app.route('/download_result')
def download_result():
    if job_result_buffer and (not progress['processing']):
        return send_file(job_result_buffer, as_attachment=True, download_name='legal_domain_results.csv', mimetype='text/csv')
    else:
        return "Result not ready", 400

if __name__ == '__main__':
    app.run(debug=True)

