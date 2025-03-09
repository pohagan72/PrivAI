from flask import Flask, render_template, request, send_file, jsonify
import pandas as pd
import requests
import ollama
import io
import threading
import subprocess
from bs4 import BeautifulSoup
import tldextract
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
import time

app = Flask(__name__)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit for file uploads
app.config['TIMEOUT'] = 30  # Increased timeout for browser operations (e.g., page loading)
app.config['SELENIUM_WAIT_TIME'] = 10  # Wait time for Selenium explicit waits AFTER page load
app.config['LOAD_WAIT_TIME'] = 10  # Wait time for the page to load before extracting

# Global variables for progress tracking and job result storage
progress_lock = threading.Lock()
progress = {
    'total': 0,
    'completed': 0,
    'processing': False,
    'error': None,
    'rate_limit_status': None  # New key for rate limit feedback
}
job_result_buffer = None

# Hardcoded Azure credentials
AZURE_OPENAI_ENDPOINT = "https://ls-s-eus-paulohagan-openai.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-08-01-preview"
AZURE_OPENAI_API_KEY = "58f022d5560f4b3c99834c9ff5b8655d"

prompt = """Carefully review the entirety of the website text provided between the tick marks. Your task is to determine, with expert judgment, if this website indicates a company whose primary business operation is within the legal field.

A company whose primary business operation is within the legal field will have a preponderance of terms in the text like:
•       Attorneys
•       Legal advice
•       Ediscovery
•       Ip law
•       Law
•       Litigation
•       Practice areas
•       Paralegal services
•       Legal staffing
•       Law school

I want only a one-word response generated based on your expert opinion.
•   If the website's primary business area is obviously in the practice or business of law, output only the word “yes.”
•   Otherwise, output only the word “no”

Never output anything more than the single word response.
"""

def classify_text_azure(text):
    if not text.strip():
        return "unsure"

    payload = {
        "messages": [
            {"role": "user", "content": f"{prompt}\n\n ```{text}```"}
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_API_KEY
    }

    max_retries = 5
    base_sleep_time = 10

    for attempt in range(max_retries):
        try:
            with progress_lock:
                progress['rate_limit_status'] = None

            response = requests.post(AZURE_OPENAI_ENDPOINT, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            answer = data["choices"][0]["message"]["content"].strip().lower()
            time.sleep(1)  # Small pause even on success

            return answer if answer in ["yes", "no", "unsure"] else "unsure"
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                retry_after = e.response.headers.get('Retry-After')
                sleep_time = int(retry_after) if retry_after and retry_after.isdigit() else base_sleep_time

                with progress_lock:
                    progress['rate_limit_status'] = f"Rate limit hit. Retrying in {sleep_time} seconds... (Attempt {attempt + 1}/{max_retries})"
                time.sleep(sleep_time)
            else:
                return "unsure"
        except Exception:
            if attempt == max_retries - 1:
                return "unsure"
            time.sleep(base_sleep_time)

    return "unsure"

def fetch_with_selenium(url):
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = None
    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(app.config['TIMEOUT'])
        driver.get(url)

        time.sleep(app.config['LOAD_WAIT_TIME'])

        wait = WebDriverWait(driver, app.config['SELENIUM_WAIT_TIME'])
        wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return ' '.join(soup.stripped_strings)
    except TimeoutException:
        return "Browser Timeout Error"
    except WebDriverException:
        return "Browser Driver Error"
    finally:
        if driver:
            driver.quit()

def process_domain(domain):
    try:
        fetch_url = f"http://{domain}" if not domain.startswith(('http://', 'https://')) else domain
        text = fetch_with_selenium(fetch_url)

        if text.startswith("Browser"):
            return text  # Return error message (e.g., "Browser Timeout Error")

        result = classify_text_azure(text)  # No longer storing extracted text

        return result
    except Exception as e:
        return f"Processing Error: {e}"

def background_process(domains):
    global job_result_buffer
    results = []

    for domain in domains:
        result = process_domain(domain)
        results.append(result)

        with progress_lock:
            progress['completed'] += 1

    final_results = ["Error" if r.startswith("Processing Error") or r.startswith("Browser") else r for r in results]

    try:
        df = pd.DataFrame({'domain': domains, 'legal_classification': final_results})
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False)
        buffer.seek(0)
        job_result_buffer = buffer
    except Exception as e:
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
            df = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)

            if 'Domain' not in df.columns:
                error = 'The file does not contain a "Domain" column.'
                return render_template('index.html', error=error, progress=progress)

            domains = df['Domain'].astype(str).tolist()

            with progress_lock:
                progress.update({'total': len(domains), 'completed': 0, 'processing': True, 'error': None})

            thread = threading.Thread(target=background_process, args=(domains,))
            thread.start()

            return render_template('index.html', message="Processing started.", progress=progress)
        except Exception as e:
            progress['processing'] = False
            progress['error'] = str(e)
            error = f"Processing error: {e}"
    return render_template('index.html', error=error, progress=progress)

@app.route('/progress')
def get_progress():
    return jsonify(progress)

@app.route('/download_result')
def download_result():
    return send_file(job_result_buffer, as_attachment=True, download_name='legal_domain_results.csv', mimetype='text/csv') if job_result_buffer else ("Result not ready", 400)

if __name__ == '__main__':
    app.run(debug=True)
