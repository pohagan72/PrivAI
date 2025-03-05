
# Domain Verifier: Legal Domain Analyzer

This tool analyzes a list of domains from a CSV or Excel file and determines whether they primarily operate in the legal field. It leverages web scraping, natural language processing, and the Ollama language model to classify each domain.

![image](https://github.com/user-attachments/assets/ce3e5606-797c-4b07-84a1-0b116176dae8)


## Features

*   **File Upload:** Accepts CSV and Excel files containing a list of domains.
*   **Web Scraping:** Extracts text content from websites using `requests` and `Beautiful Soup`. Uses `Selenium` as a fallback for JavaScript-heavy sites.
*   **Legal Classification:** Uses the Ollama `llama3:8b` model to classify website content as legal or non-legal.
*   **Parallel Processing:** Uses a `ThreadPoolExecutor` to process multiple domains concurrently, improving performance.
*   **Progress Tracking:** Provides real-time progress updates during the analysis.
*   **Downloadable Results:** Generates a CSV file containing the domains and their classifications.

## Requirements

Before using this tool, ensure you have the following installed:

*   **Python 3.6+**
*   **Ollama:** [https://ollama.com/](https://ollama.com/)
*   **Chrome Browser:** (Selenium requires Chrome)

## Installation

1.  **Clone the repository:**

    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create a virtual environment (recommended):**

    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Linux/macOS
    venv\Scripts\activate  # On Windows
    ```

3.  **Install the required Python packages:**

    ```bash
    pip install -r requirements.txt
    ```

## Usage

1.  **Start the Ollama server:**

    ```bash
    ollama serve
    ```

    *   **Note:** The application attempts to start Ollama, but it's best to start it manually to ensure proper setup.

2.  **Run the Flask application:**

    ```bash
    python main.py
    ```

3.  **Open the application in your web browser:**

    *   Navigate to `http://127.0.0.1:5000/` (or the address shown in the console).

4.  **Upload your CSV or Excel file:**

    *   The file should contain a list of domains in the first column.

5.  **Click "Start Analysis."**

6.  **Monitor the progress:**

    *   The page will display the progress of the analysis.

7.  **Download the results:**

    *   Once the analysis is complete, a "Download Results" button will appear.
    *   Click the button to download the CSV file containing the domains and their legal classifications.

## Configuration

The following configuration options can be adjusted in `main.py`:

*   `MAX_CONTENT_LENGTH`: Maximum file upload size (default: 16MB).
*   `TIMEOUT`: Timeout for browser operations (default: 15 seconds).
*   `WORKERS`: Number of worker threads for parallel processing (default: 10).
*   `prompt`: The prompt used for the Ollama model, defining the classification task.

## Error Handling

*   The application includes error handling for common issues, such as invalid domains, request failures, and Ollama errors.
*   Error messages are displayed in the web interface.

## Dependencies

*   Flask
*   pandas
*   requests
*   ollama
*   beautifulsoup4
*   tldextract
*   selenium
*   webdriver-manager

## Disclaimer

This tool provides classifications based on an AI model and web scraping. It should not be considered a substitute for professional legal advice. Always consult with a qualified legal expert for definitive legal determinations.
