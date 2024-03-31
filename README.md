# AcademicPaperFinder

# Academic Paper Search Helper

This script provides an interface to search for academic papers from multiple sources including IEEE Xplore, arXiv, PubMed, CrossRef, and more. It uses a sequential combined search strategy to go through the strategies one by one until the requested number of paper abstracts are found.

## Setup

1. Clone the repository to your local machine.
2. Install the required Python packages using the `requirements.txt` file:
```
pip install -r requirements.txt
```

3. Set up your environment variables by copying the `.env` template to your project root and filling in your API keys and email for PubMed.
```
cp env_files/local.env .env
```

Edit `.env` with your actual credentials.

## Usage

Initialize the `SearchHelper` with the desired search strategies in a preferred order. Then, execute a search with a query and the number of abstracts you wish to retrieve.

Example:
```python
from search_helper import SearchHelper

helper = SearchHelper()
helper.set_sequential_combined_strategy(["ieee", "arxiv"])
papers = helper.execute("Artificial Intelligence", 10)
for paper in papers:
 print(paper)
