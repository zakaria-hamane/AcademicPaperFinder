import requests
import re
from typing import List, Dict, Optional, Type
from abc import ABC, abstractmethod
import os
import time
import feedparser
from datetime import datetime
from Bio import Entrez
import html
import logging


logger = logging.getLogger(__name__)

class SearchStrategy(ABC):
    @abstractmethod
    def search_papers(self, query: str, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        pass


class SemanticSearchStrategy(SearchStrategy):
    def __init__(self):
        self.S2_API_KEYS = [os.getenv(f"S2_API_KEY_{i}") for i in range(1) if os.getenv(f"S2_API_KEY_{i}") is not None]

    def search_papers(self, query: str, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        headers = {}
        params = {
            "query": query,
            "limit": 100,  # Request as many as possible to minimize API calls
            "fields": "title,abstract,isOpenAccess,url,authors,year",
            "offset": 0,
            "year": "2015-",
        }
        papers = []
        for api_key in self.S2_API_KEYS:
            headers['x-api-key'] = api_key
            while len(papers) < number_of_abstracts:
                try:
                    response = requests.get(url, headers=headers, params=params)
                    if response.status_code == 200:
                        response_json = response.json()
                        for paper in response_json.get("data", []):
                            if paper.get("abstract"):
                                papers.append({
                                    "id": paper.get("paperId"),
                                    "title": paper.get("title"),
                                    "authors": ", ".join([author['name'] for author in paper.get("authors", [])]),
                                    "url": paper.get("url"),
                                    "abstract": paper.get("abstract"),
                                    "year": paper.get("year")
                                })
                                if len(papers) == number_of_abstracts:
                                    return papers
                        params["offset"] += params["limit"]
                    else:
                        logger.warning(f"API key {api_key} exceeded its rate limits or another error occurred.")
                        break  # Move to the next API key if current one fails
                except Exception as e:
                    logger.error(f"An error occurred with API key {api_key}: {e}")
                    break
        time.sleep(1)
        return papers[:number_of_abstracts]


class CrossRefStrategy(SearchStrategy):
    def __init__(self):
        self.base_url = "https://api.crossref.org/works"

    def search_papers(self, query: str, number_of_abstracts: int = 25) -> List[Dict]:
        base_url = self.base_url
        papers = []
        offset = 0  # Initialize offset to start from the beginning
        params = {
            "query": query,
            "rows": 100,  # Fetch more results initially
            "filter": "from-pub-date:2015",
            "offset": offset
        }
        try:
            while len(papers) < number_of_abstracts:
                response = requests.get(base_url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    for item in data['message']['items']:
                        abstract_cleaned = re.sub('<[^<]+?>|\s+', ' ', item.get('abstract', "")).strip() if 'abstract' in item else ""
                        if abstract_cleaned:
                            paper = {
                                "id": item['DOI'],
                                "title": item['title'][0] if item.get('title') else "No title available",
                                "authors": ", ".join([f"{author['given']} {author['family']}" for author in item.get('author', [])]),
                                "url": item['URL'] if item.get('URL') else "No URL available",
                                "abstract": abstract_cleaned,
                                "year": item['created']['date-parts'][0][0] if item.get('created') else "No year available"
                            }
                            papers.append(paper)
                            # Break if we've collected enough papers with abstracts
                            if len(papers) >= number_of_abstracts:
                                return papers[:number_of_abstracts]
                    params["offset"] += 100  # Update offset to fetch the next batch of results
                else:
                    print("Failed to fetch papers from CrossRef.")
                    break  # Exit the loop if there's an error
        except Exception as e:
            print(f"An error occurred while fetching papers from CrossRef: {e}")

        return papers[:number_of_abstracts]



class OpenAlexSearchStrategy(SearchStrategy):
    def __init__(self):
        self.base_url = "https://api.openalex.org/works"

    def search_papers(self, query: str, is_open_access: Optional[bool] = False, number_of_papers: int = 25) -> List[Dict]:
        params = {
            "search": query,
            "filter": "from_publication_date:2015-01-01",
            "mailto": os.getenv("SS_EMAIL"),
            "per_page": number_of_papers
        }
        if is_open_access:
            params["filter"] += ",is_oa:true"
        else:
            params["filter"] += ",is_oa:false"
        response = requests.get(self.base_url, params=params)
        results = []
        if response.status_code == 200:
            data = response.json()
            for item in data['results']:
                # Process abstract from the inverted index
                abstract_inverted_index = item.get('abstract_inverted_index', {})
                abstract_text = self._process_abstract(abstract_inverted_index)

                # Extract authors
                authors = ', '.join([author['display_name'] for author in item.get('authorships', []) if 'display_name' in author])

                # Prepare the dictionary for each paper
                paper_details = {
                    "id": item['id'],
                    "title": item['display_name'],
                    "authors": authors,
                    "url": item['doi'],
                    "abstract": abstract_text,
                    "year": item.get('publication_year', None)
                }
                results.append(paper_details)
        else:
            print(f"Error: {response.status_code}")

        return results

    def _process_abstract(self, abstract_inverted_index: Optional[Dict[str, List[int]]]) -> str:
        """Reconstruct abstract text from the inverted index."""
        if abstract_inverted_index is None:
            return "Abstract not available."
        sorted_words = sorted(abstract_inverted_index.items(), key=lambda item: item[1])
        abstract_text = ' '.join([word for word, positions in sorted_words])
        return abstract_text


class CoreSearchStrategy(SearchStrategy):
    def __init__(self):
        # Assuming CORE_API_KEY is stored as an environment variable
        self.CORE_API_KEY = os.getenv("CORE_API_KEY")

    def search_papers(self, query: str, is_open_access: bool = False, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        base_url = "https://api.core.ac.uk/v3/search/works"
        headers = {"Authorization": f"Bearer {self.CORE_API_KEY}"}
        params = {
            "q": query,
            "limit": 100,  # Request as many as possible to minimize API calls
            "offset": 0,
            "isOpenAccess": is_open_access  # Added is_open_access parameter
        }
        papers = []

        while len(papers) < number_of_abstracts:
            try:
                response = requests.get(base_url, headers=headers, params=params)
                if response.status_code == 200:
                    papers_data = response.json()['results']
                    for paper in papers_data:
                        year = paper.get('yearPublished', None)
                        if year and year >= 2015:
                            if paper.get('abstract'):
                                papers.append({
                                    "id": paper.get('doi', 'No doi available'),
                                    "title": paper.get('title', 'No title available'),
                                    "authors": ", ".join([author['name'] for author in paper.get('authors', [])]),
                                    "url": paper.get('downloadUrl', 'No downloadUrl available'),
                                    "abstract": paper['abstract'],
                                    "year": paper.get('yearPublished', 'No year available')
                                })
                                if len(papers) >= number_of_abstracts:
                                    return papers
                    params["offset"] += params["limit"]
                else:
                    print(f"Error fetching data from CORE API: {response.status_code}")
                    break  # Break the loop if there's an error
            except Exception as e:
                print(f"An error occurred while fetching data from CORE API: {e}")
                break
        return papers[:number_of_abstracts] if papers else None


class ArxivSearchStrategy(SearchStrategy):
    def __init__(self):
        self.base_url = "http://export.arxiv.org/api/query"

    def search_papers(self, query: str, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        params = {
            "search_query": query,
            "start": 0,
            "max_results": number_of_abstracts * 5  # Increase max_results as some may be filtered out
        }
        papers = []

        try:
            response = requests.get(self.base_url, params=params)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                for entry in feed.entries:
                    published_year = datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%SZ').year
                    if published_year >= 2015:
                        paper_info = {
                            "id": entry.id.split('/abs/')[-1],
                            "title": entry.title,
                            "authors": ", ".join([author.name for author in entry.authors]),
                            "url": entry.link,
                            "abstract": entry.summary,
                            "year": published_year
                        }
                        papers.append(paper_info)
                        if len(papers) >= number_of_abstracts:
                            break
            else:
                print(f"Error fetching data from arXiv API: {response.status_code}")
                return None
        except Exception as e:
            print(f"An error occurred while fetching data from arXiv API: {e}")
            return None

        # Only return the number of abstracts requested
        return papers[:number_of_abstracts]


class PubMedSearchStrategy(SearchStrategy):
    def __init__(self):
        Entrez.email = os.getenv("SS_EMAIL")

    def clean_html(self, text: str) -> str:
        """Remove HTML tags and entities from the given text."""
        # First, convert HTML entities to text
        text = html.unescape(text)
        # Then remove any remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        return text

    def search_papers(self, query: str, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        papers = []
        term = f"{query} AND (2015[PDAT] : 3000[PDAT])"
        try:
            handle = Entrez.esearch(db="pubmed", term=term, retmax=number_of_abstracts, usehistory="y")
            record = Entrez.read(handle)
            id_list = record.get("IdList")
            handle.close()

            if id_list:
                handle = Entrez.efetch(db="pubmed", id=",".join(id_list), retmode="xml")
                articles = Entrez.read(handle)
                handle.close()

                for article in articles['PubmedArticle']:
                    article_info = article['MedlineCitation']['Article']
                    paper_info = {
                        "id": f"{article['MedlineCitation']['PMID']}",
                        "title": self.clean_html(article_info.get('ArticleTitle', 'No title available')),
                        "authors": ", ".join([author.get('LastName', '') + " " + author.get('ForeName', '') for author in article_info.get('AuthorList', [])]),
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{article['MedlineCitation']['PMID']}/",
                        "abstract": self.clean_html(" ".join([abstract_text for abstract_text in article_info.get('Abstract', {}).get('AbstractText', [])])),
                        "year": article_info.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {}).get('Year', 'No year available'),
                    }
                    if paper_info["year"].isdigit() and int(paper_info["year"]) >= 2015:
                        papers.append(paper_info)
        except Exception as e:
            print(f"An error occurred while fetching data from PubMed: {e}")
            return None
        return papers


class SpringerSearchStrategy(SearchStrategy):
    def __init__(self):
        self.api_key = os.getenv("SPRINGER_API_KEY")
        self.base_url = "http://api.springernature.com/meta/v1/json"

    def search_papers(self, query: str, is_open_access: Optional[bool] = False, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        params = {
            "q": query,
            "p": 100,  # Maximum allowed by Springer
            "api_key": self.api_key
        }
        papers = []

        try:
            response = requests.get(self.base_url, params=params)
            if response.status_code == 200:
                response_json = response.json()
                for record in response_json.get("records", []):
                    publication_date = int(datetime.strptime(record.get("publicationDate", "1900"), '%Y-%m-%d').year)
                    open_access = record.get("openaccess", "false") == str(is_open_access).lower()
                    if publication_date >= 2015:
                        paper_info = {
                            "id": record.get("doi"),
                            "title": record.get("title"),
                            "authors": ", ".join([author["creator"] for author in record.get("creators", []) if "creator" in author]),
                            "url": record.get("url", [{"value": ""}])[0].get("value"),
                            "abstract": record.get("abstract"),
                            "year": publication_date
                        }
                        papers.append(paper_info)
                        if len(papers) >= number_of_abstracts:
                            break
            else:
                print(f"Error fetching data from Springer API: {response.status_code}")
                return None
        except Exception as e:
            print(f"An error occurred while fetching data from Springer API: {e}")
            return None

        return papers if papers else None


class PLOSSearchStrategy(SearchStrategy):
    def __init__(self):
        self.base_url = "http://api.plos.org/search"

    def search_papers(self, query: str, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        query_filters = [
            f"article_type:\"Research Article\"",  # Assuming research articles are of interest
            "publication_date:[2015-01-01T00:00:00Z TO *]"  # From 2015 onwards
        ]
        query_with_filters = f"({query}) AND {' AND '.join(query_filters)}"

        params = {
            "q": query_with_filters,
            "start": 0,
            "rows": 100,  # Fetch more results initially
            "wt": "json",
            "fl": "id,title,author,abstract,publication_date,article_type,doi,link"
        }
        papers = []

        try:
            response = requests.get(self.base_url, params=params)
            if response.status_code == 200:
                response_json = response.json()
                for doc in response_json['response']['docs']:
                    if len(papers) >= number_of_abstracts:
                        break  # Stop if we have enough articles

                    publication_date = doc.get("publication_date", "1900-01-01T00:00:00Z")
                    year_published = datetime.strptime(publication_date, "%Y-%m-%dT%H:%M:%SZ").year

                    if year_published >= 2015:
                        paper_info = {
                            "id": doc.get("id"),
                            "title": doc.get("title"),
                            "authors": ", ".join(doc.get("author", [])),
                            "url": f"https://doi.org/{doc.get('id')}",
                            "abstract": doc.get("abstract", ["No abstract available"])[0],
                            "year": year_published
                        }
                        papers.append(paper_info)
            else:
                print(f"Error fetching data from PLOS API: {response.status_code}")
                return None
        except Exception as e:
            print(f"An error occurred while fetching data from PLOS API: {e}")
            return None

        return papers[:number_of_abstracts]


class IEEESearchStrategy(SearchStrategy):
    def __init__(self):
        self.api_key = "muv343srt4jrc52d38p3n4s3"
        self.base_url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

    def search_papers(self, query: str, is_open_access: bool = False, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        params = {
            "querytext": query,
            "apikey": self.api_key,
            "start_record": 1,
            "max_records": 100,  # Adjust based on how many records you want to fetch in a single request
            "content_type": "journals",
        }
        papers = []

        try:
            while len(papers) < number_of_abstracts:
                response = requests.get(self.base_url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    for article in data.get("articles", []):
                        year_published = int(article.get("publicationYear", "0"))
                        access_type = article.get("accessType", "")

                        # Check if the paper meets the open access and year criteria
                        if year_published >= 2015 and (not is_open_access or access_type in ["Open Access", "Ephemera"]):
                            paper_info = {
                                "id": article.get("articleNumber", ""),
                                "title": article.get("title", ""),
                                "authors": ", ".join([author.get("fullName", "") for author in article.get("authors", {}).get("authors", [])]),
                                "abstract": article.get("abstract", ""),
                                "year": year_published,
                                "accessType": access_type,
                                "url": f"https://ieeexplore.ieee.org/document/{article.get('articleNumber', '')}"
                            }
                            papers.append(paper_info)
                            if len(papers) >= number_of_abstracts:
                                break

                    # Prepare for the next batch of articles if needed
                    params["start_record"] += 100
                else:
                    print(f"Error fetching data from IEEE: {response.status_code}")
                    break
        except Exception as e:
            print(f"An error occurred while fetching data from IEEE: {e}")
            return None

        return papers[:number_of_abstracts]


class ScopusSearchStrategy(SearchStrategy):
    def __init__(self):
        self.api_key = os.getenv("SCOPUS_API_KEY")
        self.base_url = "https://api.elsevier.com/content/search/scopus"

    def search_papers(self, query: str, is_open_access: bool = False, number_of_abstracts: int = 25) -> Optional[List[Dict]]:
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json"
        }
        # Incorporate the open access and publication year filter into the query if required
        open_access_filter = "AND (OPENACCESS(1))" if is_open_access else ""
        year_filter = "AND PUBYEAR > 2014"
        full_query = f"{query} {open_access_filter} {year_filter}"

        params = {
            "query": full_query,
            "count": number_of_abstracts,  # Number of results to return
            "field": "dc:title,dc:creator,dc:description,prism:publicationName,prism:doi,prism:url,prism:coverDate"  # Including prism:coverDate for year
        }
        papers = []

        try:
            response = requests.get(self.base_url, headers=headers, params=params)
            if response.status_code == 200:
                response_json = response.json()
                for entry in response_json.get("search-results", {}).get("entry", []):
                    # Extracting the year from the cover date
                    cover_date = entry.get("prism:coverDate", "")
                    year = cover_date.split('-')[0] if cover_date else "No year available"
                    paper_info = {
                        "id": entry.get("prism:doi"),
                        "title": entry.get("dc:title"),
                        "authors": entry.get("dc:creator"),
                        "url": f"https://doi.org/{entry.get('prism:doi')}",
                        "abstract": entry.get("dc:description"),
                        "year": year
                    }
                    papers.append(paper_info)
            else:
                print(f"Error fetching data from Scopus API: {response.status_code}")
                return None
        except Exception as e:
            print(f"An error occurred while fetching data from Scopus API: {e}")
            return None

        return papers


class SequentialCombinedSearchStrategy(SearchStrategy):
    def __init__(self, strategies: List[SearchStrategy]):
        """
        Initializes the combined search strategy with a list of strategies.
        :param strategies: List of search strategies to use in sequence.
        """
        self.strategies = strategies

    def search_papers(self, query: str, number_of_abstracts: int = 25) -> List[Dict]:
        papers = []
        for strategy in self.strategies:
            remaining_abstracts = number_of_abstracts - len(papers)
            if remaining_abstracts <= 0:
                break
            strategy_papers = strategy.search_papers(query, remaining_abstracts)
            if strategy_papers is not None:  # Check if strategy_papers is not None
                papers += strategy_papers
        return papers[:number_of_abstracts]

# Modify SearchHelper to include SequentialCombinedSearchStrategy
class SearchHelper:
    def __init__(self, strategy: Type[SearchStrategy] = None):
        self.strategies: Dict[str, Type[SearchStrategy]] = {
            "semantic_scholar": SemanticSearchStrategy,
            "cross_ref": CrossRefStrategy,
            "open_alex": OpenAlexSearchStrategy,
            "core": CoreSearchStrategy,
            "plos": PLOSSearchStrategy,
            "springer": SpringerSearchStrategy,
            "arxiv": ArxivSearchStrategy,
            "pubmed": PubMedSearchStrategy,
            "ieee": IEEESearchStrategy,
            "scopus": ScopusSearchStrategy,
            "sequential_combined": SequentialCombinedSearchStrategy  # Add SequentialCombinedSearchStrategy
        }
        if strategy:
            self.strategy = self.initialize_strategy(strategy)
        else:
            self.strategy = None

    def initialize_strategy(self, strategy_key: Type[SearchStrategy]) -> SearchStrategy:
        if strategy_key in self.strategies:
            return strategy_key()  # Initialize the strategy if it's a class
        elif isinstance(strategy_key, SequentialCombinedSearchStrategy):
            return strategy_key  # Use the instance directly if it's already an instance
        else:
            raise ValueError(f"Strategy '{strategy_key}' not recognized. Please choose from {list(self.strategies.keys())}.")

    def set_sequential_combined_strategy(self, strategy_keys: List[str]):
        """
        Initialize SequentialCombinedSearchStrategy with a list of strategies specified by keys.
        :param strategy_keys: List of keys identifying the strategies to combine.
        """
        strategies = [self.strategies[key]() for key in strategy_keys]
        self.strategy = SequentialCombinedSearchStrategy(strategies)

    def execute(self, search_query: str, number_of_abstracts: int = 25) -> List[Dict]:
        if not self.strategy:
            logger.error("Search strategy not initialized.")
            return []
        return self.strategy.search_papers(search_query, number_of_abstracts)
