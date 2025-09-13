import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
from typing import List, Dict
import json

class LinkedInPublicScraper:
    def __init__(self, delay: float = 2.5):
        self.delay = delay  # Delay between requests in seconds
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        self.data = []
        
    def search_profiles(self, prompt: str, location: str, max_results: int = 50) -> List[Dict]:
        """
        Search LinkedIn profiles based on prompt and location
        """
        # Format search parameters
        search_params = {
            'keywords': prompt,
            'location': location,
            'page': 1
        }
        
        results_collected = 0
        
        while results_collected < max_results:
            # Build search URL
            search_url = self.build_search_url(search_params)
            
            try:
                # Respectful delay between requests
                time.sleep(self.delay)
                
                # Send request
                response = self.session.get(search_url, headers=self.headers)
                
                if response.status_code != 200:
                    print(f"Error: Received status code {response.status_code}")
                    break
                    
                # Parse results
                profiles = self.parse_search_results(response.text)
                
                if not profiles:
                    print("No more profiles found")
                    break
                
                # Process each profile
                for profile_url in profiles:
                    if results_collected >= max_results:
                        break
                        
                    profile_data = self.scrape_profile(profile_url)
                    if profile_data and self.is_public_data(profile_data):
                        self.data.append(profile_data)
                        results_collected += 1
                
                # Move to next page
                search_params['page'] += 1
                
            except Exception as e:
                print(f"Error during search: {e}")
                break
        
        return self.data
    
    def build_search_url(self, params: Dict) -> str:
        """Construct LinkedIn search URL from parameters"""
        base_url = "https://www.linkedin.com/search/results/people/"
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{query_string}"
    
    def parse_search_results(self, html: str) -> List[str]:
        """Extract profile URLs from search results page"""
        soup = BeautifulSoup(html, 'html.parser')
        profile_links = []
        
        # Find all profile result elements - note: class names may change
        results = soup.select('.reusable-search__result-container')
        
        for result in results:
            profile_link = result.select_one('.app-aware-link')
            if profile_link and profile_link.get('href'):
                profile_url = profile_link['href'].split('?')[0]
                if '/in/' in profile_url:
                    profile_links.append(profile_url)
        
        return profile_links
    
    def scrape_profile(self, profile_url: str) -> Dict:
        """Scrape public data from a LinkedIn profile"""
        try:
            time.sleep(self.delay)  # Respectful delay
            response = self.session.get(profile_url, headers=self.headers)
            
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract basic information
            name = self.extract_name(soup)
            headline = self.extract_headline(soup)
            public_contact = self.extract_public_contact(soup)
            
            profile_data = {
                'name': name,
                'headline': headline,
                'profile_url': profile_url,
                'public_contact': public_contact,
                'timestamp': time.time()
            }
            
            return profile_data
            
        except Exception as e:
            print(f"Error scraping profile {profile_url}: {e}")
            return None
    
    def extract_public_contact(self, soup: BeautifulSoup) -> Dict:
        """Extract publicly available contact information"""
        contact_info = {}
        
        # Look for public contact information
        contact_section = soup.select('.ci-public')
        if contact_section:
            # Extract email if publicly visible
            email_element = contact_section[0].select('.ci-email')
            if email_element:
                email = email_element[0].text.strip()
                if self.validate_email(email):
                    contact_info['email'] = email
            
            # Extract other public contact details
            website_element = contact_section[0].select('.ci-websites')
            if website_element:
                contact_info['website'] = website_element[0].text.strip()
        
        return contact_info
    
    def validate_email(self, email: str) -> bool:
        """Validate email format using regex"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def is_public_data(self, profile_data: Dict) -> bool:
        """Verify that data is truly public"""
        # Implement checks to ensure we're not accidentally collecting private data
        return True  # Simplified for example
    
    def save_data(self, filename: str):
        """Save scraped data to file"""
        df = pd.DataFrame(self.data)
        df.to_csv(filename, index=False)
        print(f"Data saved to {filename}")

# Example usage
if __name__ == "__main__":
    scraper = LinkedInPublicScraper(delay=5.0)
    results = scraper.search_profiles(
        prompt="software engineer",
        location="gurugram",
        max_results=10
    )
    scraper.save_data("linkedin_public_contacts.csv")