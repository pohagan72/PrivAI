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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit for file uploads
app.config['TIMEOUT'] = 15  # Timeout in seconds for browser operations (e.g., page loading)
app.config['WORKERS'] = 10  # Number of worker threads to use for parallel processing of domains

# Global variables for progress tracking and job result storage
progress_lock = threading.Lock()  # A lock to protect access to the 'progress' dictionary from multiple threads
progress = {
    'total': 0,  # Total number of domains to process
    'completed': 0,  # Number of domains processed so far
    'processing': False,  # Flag indicating whether processing is currently in progress
    'error': None  # Any error message that occurred during processing
}
# This will hold the CSV result once processing is finished.
job_result_buffer = None

# Prompt for Ollama - This is the instruction given to the Ollama model.
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
    """Checks if Ollama is running by attempting to pull a model."""
    try:
        ollama.pull("llama3:8b")  # Attempts to pull the llama3:8b model.  If Ollama isn't running, this will fail.
        return True
    except Exception as e:
        print(f"Ollama check failed: {e}")
        return False

def start_ollama():
    """Starts the Ollama server using subprocess."""
    try:
        subprocess.Popen(['ollama', 'serve'])  # Starts the Ollama server in a separate process.
        return True
    except Exception as e:
        print(f"Failed to start Ollama: {e}")
        return False

def fetch_with_selenium(url):
    """Fetches content from a URL using Selenium and extracts text."""
    options = ChromeOptions()
    options.add_argument("--headless")  # Run Chrome in headless mode (no GUI)
    options.add_argument("--no-sandbox")  # Bypass the sandbox for security reasons (needed in some environments)
    options.add_argument("--disable-dev-shm-usage")  # Avoid issues with shared memory
    options.add_argument("--window-size=1920,1080")  # Set the window size for rendering
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )  # Set a user agent to mimic a browser

    driver = None
    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)  # Initialize the Chrome driver
        driver.set_page_load_timeout(app.config['TIMEOUT'])  # Set a timeout for page loading
        driver.get(url)  # Navigate to the URL
        soup = BeautifulSoup(driver.page_source, 'html.parser')  # Parse the HTML content using BeautifulSoup
        return ' '.join(soup.stripped_strings)  # Extract all text from the page and join it into a single string
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
            driver.quit()  # Close the browser window

def fetch_and_extract_text(url):
    """Fetches content from a URL and extracts text, with fallback to Selenium."""
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url  # Add http:// if the URL doesn't have a scheme

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        try:
            response = requests.get(url, headers=headers, timeout=app.config['TIMEOUT'])  # Make an HTTP GET request
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            # Basic heuristic: if content hints at heavy JavaScript and is very short, try Selenium.
            if "javascript" in response.text.lower() and len(response.text) < 1000:
                print(f"Trying Selenium for JavaScript content: {url}")
                return fetch_with_selenium(url)  # If the page seems to rely heavily on JavaScript, use Selenium
            soup = BeautifulSoup(response.content, 'html.parser')  # Parse the HTML content
            return ' '.join(soup.stripped_strings)  # Extract and return the text
        except requests.exceptions.RequestException as e:
            print(f"Requests failed for {url}, trying Selenium: {e}")
            return fetch_with_selenium(url)  # If the request fails, fall back to Selenium
    except Exception as e:
        print(f"Error extracting text from {url}: {e}")
        return f"Extraction Error: {e}"

def classify_text(text):
    """Classifies the text using the Ollama model."""
    if not text.strip():
        return "unsure"  # Return "unsure" if the text is empty or contains only whitespace
    try:
        response = ollama.chat(model='llama3:8b', messages=[
            {'role': 'user', 'content': f"{prompt}\n\n ```{text}```"}  # Send the prompt and text to the Ollama model
        ])
        return response['message']['content'].strip().lower()  # Return the model's response, stripped of whitespace and converted to lowercase
    except Exception as e:
        print(f"Ollama error: {e}")
        return "unsure"  # Return "unsure" if there's an error communicating with Ollama

def is_valid_domain(domain):
    """Validates if a domain is well-formed and appears to resolve."""
    try:
        extracted = tldextract.extract(domain)  # Extract the domain name, subdomain, and suffix
        if not extracted.domain or not extracted.suffix:
            return False  # Return False if the domain or suffix is missing
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.head(f"http://{domain}", headers=headers, timeout=5, allow_redirects=True)  # Make a HEAD request to check if the domain resolves
        return response.status_code < 500  # Return True if the status code is less than 500 (success)
    except requests.exceptions.RequestException:
        return False  # Return False if there's a request exception (e.g., domain doesn't resolve)
    except Exception as e:
        print(f"Unexpected error validating domain {domain}: {e}")
        return False  # Return False for any other unexpected errors

def process_domain(domain, results, idx):
    """Processes a single domain and stores the result."""
    try:
        if not is_valid_domain(domain):
            with progress_lock:
                results[idx] = "invalid domain"  # Mark the domain as invalid
                progress['completed'] += 1  # Increment the completed count
            return

        fetch_url = domain if domain.startswith(('http://', 'https://')) else 'http://' + domain  # Construct the URL
        text = fetch_and_extract_text(fetch_url)  # Fetch and extract the text from the URL
        if text.startswith("Request Error:") or text.startswith("Extraction Error:") or text.startswith("Browser"):
            with progress_lock:
                results[idx] = text  # Store the error message
                progress['completed'] += 1  # Increment the completed count
            return

        result = classify_text(text)  # Classify the text using the Ollama model
        with progress_lock:
            results[idx] = result  # Store the classification result
            progress['completed'] += 1  # Increment the completed count
    except Exception as e:
        print(f"Error processing {domain}: {e}")
        with progress_lock:
            results[idx] = f"Processing Error: {e}"  # Store the error message
            progress['error'] = str(e)  # Store the error in the global progress dictionary
            progress['completed'] += 1  # Increment the completed count

def background_process(domains):
    """Background thread function to process domains using a ThreadPoolExecutor."""
    global job_result_buffer
    total = len(domains)
    results = [None] * total  # Initialize a list to store the results for each domain
    # Check and (if needed) start Ollama before processing
    if not check_ollama_running():
        if not start_ollama():
            with progress_lock:
                progress['processing'] = False
                progress['error'] = "Ollama is not running and could not be started. Please ensure Ollama is installed and running."
            return

    with ThreadPoolExecutor(max_workers=app.config['WORKERS']) as executor:  # Use a ThreadPoolExecutor to process domains in parallel
        for idx, domain in enumerate(domains):
            executor.submit(process_domain, domain, results, idx)  # Submit each domain to the executor
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
        df = pd.DataFrame({'domain': domains, 'legal_classification': final_results})  # Create a Pandas DataFrame from the results
        buffer = io.BytesIO()  # Create an in-memory buffer to store the CSV data
        df.to_csv(buffer, index=False)  # Write the DataFrame to the buffer as a CSV file
        buffer.seek(0)  # Reset the buffer's position to the beginning
        job_result_buffer = buffer  # Store the buffer in the global variable
    except Exception as e:
        print(f"Error generating result CSV: {e}")
        with progress_lock:
            progress['error'] = str(e)  # Store the error in the global progress dictionary
    finally:
        with progress_lock:
            progress['processing'] = False  # Set the processing flag to False

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the main route for the application."""
    error = None
    if request.method == 'POST':
        file = request.files.get('file')  # Get the uploaded file
        if not file or file.filename == '':
            error = 'Please select a valid Excel or CSV file.'  # Set an error message if no file is selected
            return render_template('index.html', error=error, progress=progress)  # Render the template with the error message
        try:
            if file.filename.endswith('.xlsx'):
                df = pd.read_excel(file)  # Read the Excel file into a Pandas DataFrame
            else:
                df = pd.read_csv(file)  # Read the CSV file into a Pandas DataFrame
            
            # Assume domains are in the first column.
            domains = df.iloc[:, 0].astype(str).tolist()  # Extract the domains from the first column of the DataFrame
            domains = [d.strip() for d in domains]  # Remove leading/trailing whitespace from each domain

            with progress_lock:
                progress['total'] = len(domains)  # Set the total number of domains
                progress['completed'] = 0  # Reset the completed count
                progress['processing'] = True  # Set the processing flag to True
                progress['error'] = None  # Reset the error message

            # Start background processing so the HTTP request finishes immediately.
            thread = threading.Thread(target=background_process, args=(domains,))  # Create a new thread to run the background process
            thread.start()  # Start the thread

            # Render a page that will poll for progress.
            return render_template('index.html', message="File uploaded. Processing started.", progress=progress)  # Render the template with a success message
        except Exception as e:
            error = f"Processing error: {e}"  # Set an error message if there's an exception
            print(f"Error: {e}")
            with progress_lock:
                progress['processing'] = False  # Set the processing flag to False
                progress['error'] = str(e)  # Store the error in the global progress dictionary
    return render_template('index.html', error=error, progress=progress)  # Render the template with any error messages

@app.route('/progress')
def get_progress():
    """Returns the current progress as a JSON response."""
    with progress_lock:
        return jsonify(progress)  # Return the progress dictionary as a JSON response

@app.route('/download_result')
def download_result():
    """Downloads the result CSV file."""
    if job_result_buffer and (not progress['processing']):  # Check if the result buffer is available and processing is complete
        return send_file(job_result_buffer, as_attachment=True, download_name='legal_domain_results.csv', mimetype='text/csv')  # Send the CSV file as a download
    else:
        return "Result not ready", 400  # Return an error message if the result is not ready

if __name__ == '__main__':
    app.run(debug=True)  # Run the Flask application in debug mode
