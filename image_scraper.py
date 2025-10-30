#!/usr/bin/env python3
"""
Smith Pharmacy Image Scraper
A comprehensive tool to scrape product images from multiple sources for Shopify products.
"""

import csv
import requests
import time
import random
import os
import re
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup
import logging
from typing import List, Dict, Optional, Tuple
import json
from dataclasses import dataclass
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class SearchResult:
    """Represents a search result for a product image"""
    url: str
    title: str
    source: str
    confidence: float
    size: Optional[Tuple[int, int]] = None

class ImageScraper:
    """Main class for scraping product images from multiple sources"""
    
    def __init__(self, config_file: str = "scraper_config.json"):
        self.config = self.load_config(config_file)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.results = []
        self.downloaded_count = 0
        self.failed_count = 0
        self.checkpoint_cfg = self.config.get('checkpoint', {
            'enabled': False,
            'resume': False,
            'every_n_products': 20,
            'file': 'dataset/scraper_checkpoint.json',
        })

    def load_checkpoint(self) -> Optional[Dict]:
        """Load checkpoint data if enabled and present"""
        try:
            if self.checkpoint_cfg.get('enabled') and self.checkpoint_cfg.get('resume'):
                checkpoint_file = self.checkpoint_cfg.get('file')
                if checkpoint_file and os.path.exists(checkpoint_file):
                    with open(checkpoint_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
        return None

    def save_checkpoint(self, data: Dict) -> None:
        """Persist checkpoint data to disk if enabled"""
        try:
            if not self.checkpoint_cfg.get('enabled'):
                return
            checkpoint_file = self.checkpoint_cfg.get('file')
            if not checkpoint_file:
                return
            os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")

    def clear_checkpoint(self) -> None:
        """Remove checkpoint file on successful completion"""
        try:
            checkpoint_file = self.checkpoint_cfg.get('file')
            if checkpoint_file and os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
        except Exception as e:
            logger.warning(f"Failed to clear checkpoint: {e}")
        
    def load_config(self, config_file: str) -> Dict:
        """Load configuration from JSON file"""
        default_config = {
            "search_sources": {
                "google_images": True,
                "bing_images": True,
                "amazon": True,
                "manufacturer_websites": True
            },
            "search_settings": {
                "max_results_per_source": 5,
                "min_image_size": (200, 200),
                "preferred_formats": ["jpg", "jpeg", "png", "webp"],
                "delay_between_requests": 1.0,
                "max_retries": 3
            },
            "output_settings": {
                "save_images_locally": True,
                "images_folder": "scraped_images",
                "update_csv_with_urls": True,
                "backup_original_csv": True
            }
        }
        
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                # Merge with defaults
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        else:
            # Create default config file
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config
    
    def search_google_images(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Search Google Images for product images with high-resolution filtering"""
        results = []
        try:
            # Add size filter for large images
            search_url = f"https://www.google.com/search?q={quote_plus(query)}&tbm=isch&tbs=isz:l"
            response = self.session.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find image containers
            img_containers = soup.find_all('div', class_='islrc')[:max_results]
            
            for container in img_containers:
                try:
                    img_tag = container.find('img')
                    if img_tag and img_tag.get('src'):
                        img_url = img_tag['src']
                        if img_url.startswith('data:'):
                            continue  # Skip data URLs
                        
                        # Try to get higher resolution version
                        if 'googleusercontent.com' in img_url:
                            # Replace with higher resolution version
                            img_url = img_url.replace('=s', '=s0')  # Full size
                            img_url = img_url.replace('=w', '=w0')  # Full width
                        
                        # Get image title/alt text
                        title = img_tag.get('alt', '') or img_tag.get('title', '')
                        
                        # Check if it's high resolution
                        confidence = 0.8
                        if self.is_high_resolution(img_url):
                            confidence = 0.9
                        
                        results.append(SearchResult(
                            url=img_url,
                            title=title,
                            source='Google Images',
                            confidence=confidence
                        ))
                except Exception as e:
                    logger.warning(f"Error parsing Google image container: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error searching Google Images: {e}")
            
        return results
    
    def search_bing_images(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Search Bing Images for product images"""
        results = []
        try:
            search_url = f"https://www.bing.com/images/search?q={quote_plus(query)}"
            response = self.session.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find image containers
            img_containers = soup.find_all('div', class_='img_cont')[:max_results]
            
            for container in img_containers:
                try:
                    img_tag = container.find('img')
                    if img_tag and img_tag.get('src'):
                        img_url = img_tag['src']
                        if img_url.startswith('data:'):
                            continue
                        
                        title = img_tag.get('alt', '') or img_tag.get('title', '')
                        
                        results.append(SearchResult(
                            url=img_url,
                            title=title,
                            source='Bing Images',
                            confidence=0.7
                        ))
                except Exception as e:
                    logger.warning(f"Error parsing Bing image container: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error searching Bing Images: {e}")
            
        return results
    
    def search_amazon(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Search Amazon for product images with high-resolution filtering"""
        results = []
        try:
            search_url = f"https://www.amazon.com/s?k={quote_plus(query)}"
            response = self.session.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find product containers
            product_containers = soup.find_all('div', {'data-component-type': 's-search-result'})[:max_results]
            
            for container in product_containers:
                try:
                    img_tag = container.find('img', class_='s-image')
                    if img_tag and img_tag.get('src'):
                        img_url = img_tag['src']
                        
                        # Try to get higher resolution version
                        if 'media-amazon.com' in img_url:
                            # Replace with higher resolution version
                            img_url = img_url.replace('_AC_UL320_', '_AC_UL1500_')  # Higher res
                            img_url = img_url.replace('_AC_UL160_', '_AC_UL1500_')  # Higher res
                            img_url = img_url.replace('_AC_UL218_', '_AC_UL1500_')  # Higher res
                            img_url = img_url.replace('_AC_UL320_.jpg', '_AC_UL1500_.jpg')
                            img_url = img_url.replace('_AC_UL160_.jpg', '_AC_UL1500_.jpg')
                            img_url = img_url.replace('_AC_UL218_.jpg', '_AC_UL1500_.jpg')
                        
                        title = img_tag.get('alt', '')
                        
                        # Check if it's high resolution
                        confidence = 0.9
                        if self.is_high_resolution(img_url):
                            confidence = 0.95
                        
                        results.append(SearchResult(
                            url=img_url,
                            title=title,
                            source='Amazon',
                            confidence=confidence
                        ))
                except Exception as e:
                    logger.warning(f"Error parsing Amazon product container: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error searching Amazon: {e}")
            
        return results
    
    def search_unsplash(self, query: str, max_results: int = 3) -> List[SearchResult]:
        """Search Unsplash for high-quality product images"""
        results = []
        try:
            search_url = f"https://unsplash.com/s/photos/{quote_plus(query)}"
            response = self.session.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find image containers
            img_containers = soup.find_all('div', class_='MorZF')[:max_results]
            
            for container in img_containers:
                try:
                    img_tag = container.find('img')
                    if img_tag and img_tag.get('src'):
                        img_url = img_tag['src']
                        if img_url.startswith('data:'):
                            continue
                        
                        # Get high-resolution version
                        if 'unsplash.com' in img_url:
                            img_url = img_url.replace('w=400', 'w=1200')  # Higher resolution
                            img_url = img_url.replace('h=300', 'h=900')   # Higher resolution
                        
                        title = img_tag.get('alt', '') or img_tag.get('title', '')
                        
                        results.append(SearchResult(
                            url=img_url,
                            title=title,
                            source='Unsplash',
                            confidence=0.85
                        ))
                except Exception as e:
                    logger.warning(f"Error parsing Unsplash image container: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error searching Unsplash: {e}")
            
        return results
    
    def search_manufacturer_website(self, product_title: str, vendor: str, max_results: int = 3) -> List[SearchResult]:
        """Search manufacturer websites for product images"""
        results = []
        
        # Common manufacturer website patterns
        manufacturer_sites = {
            'AOR': ['aor.ca', 'aor.health'],
            'ATP': ['atpscience.com', 'atpnutrition.com'],
            'AXEL KRAFT': ['axelkraft.com', 'basicare.com'],
            'NATURE\'S SUNSHINE': ['naturessunshine.com', 'nsp.com'],
            'NOW': ['nowfoods.com', 'nowsupplements.com'],
            'THORNE': ['thorne.com', 'thorne.co'],
            'GARDEN OF LIFE': ['gardenoflife.com'],
            'NATURE\'S WAY': ['naturesway.com'],
            'SOLGAR': ['solgar.com'],
            'JARROW': ['jarrow.com']
        }
        
        if vendor.upper() not in manufacturer_sites:
            return results
            
        for site in manufacturer_sites[vendor.upper()]:
            try:
                search_url = f"https://www.{site}/search?q={quote_plus(product_title)}"
                response = self.session.get(search_url, timeout=10)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for product images (this will vary by site)
                img_tags = soup.find_all('img')[:max_results]
                
                for img_tag in img_tags:
                    if img_tag.get('src'):
                        img_url = img_tag['src']
                        if not img_url.startswith('http'):
                            img_url = urljoin(f"https://www.{site}", img_url)
                        
                        title = img_tag.get('alt', '') or img_tag.get('title', '')
                        
                        # Check if this looks like a product image
                        if any(keyword in title.lower() for keyword in ['product', 'supplement', 'vitamin', 'capsule', 'tablet']):
                            results.append(SearchResult(
                                url=img_url,
                                title=title,
                                source=f'Manufacturer ({site})',
                                confidence=0.95
                            ))
                            
            except Exception as e:
                logger.warning(f"Error searching manufacturer site {site}: {e}")
                continue
                
        return results
    
    def validate_image_url(self, url: str) -> bool:
        """Validate if the image URL is accessible and has proper format"""
        try:
            response = self.session.head(url, timeout=5)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                return any(fmt in content_type for fmt in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'])
        except:
            pass
        return False
    
    def get_image_resolution(self, url: str) -> Optional[Tuple[int, int]]:
        """Get image resolution without downloading the full image"""
        try:
            response = self.session.get(url, stream=True, timeout=10)
            if response.status_code == 200:
                # Read only the first chunk to get image dimensions
                chunk = response.raw.read(1024)
                if chunk:
                    from PIL import Image
                    import io
                    try:
                        img = Image.open(io.BytesIO(chunk))
                        return img.size
                    except:
                        pass
        except:
            pass
        return None
    
    def is_high_resolution(self, url: str, min_size: Tuple[int, int] = (300, 300)) -> bool:
        """Check if image meets minimum resolution requirements"""
        try:
            # Check URL patterns for high-res indicators
            high_res_patterns = [
                '_AC_UL1500_', '_AC_UL2000_', '_AC_UL3000_',  # Amazon high-res
                'large', 'high', 'hd', '4k', 'ultra',
                'w=800', 'w=1000', 'w=1200', 'w=1500',  # Width indicators
                'h=800', 'h=1000', 'h=1200', 'h=1500'   # Height indicators
            ]
            
            for pattern in high_res_patterns:
                if pattern in url.lower():
                    return True
            
            # Try to get actual resolution
            resolution = self.get_image_resolution(url)
            if resolution:
                width, height = resolution
                return width >= min_size[0] and height >= min_size[1]
            
        except:
            pass
        return False
    
    def download_image(self, result: SearchResult, product_handle: str) -> Optional[str]:
        """Download image and return local path"""
        try:
            if not self.validate_image_url(result.url):
                return None
                
            response = self.session.get(result.url, timeout=10)
            if response.status_code == 200:
                # Create filename
                file_extension = result.url.split('.')[-1].split('?')[0]
                if file_extension not in self.config['search_settings']['preferred_formats']:
                    file_extension = 'jpg'
                
                filename = f"{product_handle}_{self.downloaded_count}.{file_extension}"
                filepath = os.path.join(self.config['output_settings']['images_folder'], filename)
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                
                # Save image
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                self.downloaded_count += 1
                logger.info(f"Downloaded image: {filename}")
                return filepath
                
        except Exception as e:
            logger.error(f"Error downloading image from {result.url}: {e}")
            self.failed_count += 1
            
        return None
    
    def search_product_images(self, product_data: Dict) -> List[SearchResult]:
        """Search for images for a single product using all enabled sources"""
        all_results = []
        
        # Create search queries
        title = product_data.get('Title', '')
        vendor = product_data.get('Vendor', '')
        sku = product_data.get('Variant SKU', '')
        
        queries = [
            f"{title} {vendor}",
            f"{title} {sku}",
            title,
            f"{vendor} {sku}"
        ]
        
        # Remove duplicates and empty queries
        queries = list(set([q.strip() for q in queries if q.strip()]))
        
        for query in queries:
            if not query:
                continue
                
            logger.info(f"Searching for: {query}")
            
            # Search each enabled source (ordered: Google -> Amazon -> others)
            if self.config['search_sources']['google_images']:
                all_results.extend(self.search_google_images(query, self.config['search_settings']['max_results_per_source']))
                time.sleep(self.config['search_settings']['delay_between_requests'])
            
            if self.config['search_sources']['amazon']:
                all_results.extend(self.search_amazon(query, self.config['search_settings']['max_results_per_source']))
                time.sleep(self.config['search_settings']['delay_between_requests'])
            
            if self.config['search_sources']['bing_images']:
                all_results.extend(self.search_bing_images(query, self.config['search_settings']['max_results_per_source']))
                time.sleep(self.config['search_settings']['delay_between_requests'])
            
            if self.config['search_sources']['unsplash']:
                all_results.extend(self.search_unsplash(query, 3))
                time.sleep(self.config['search_settings']['delay_between_requests'])
            
            if self.config['search_sources']['manufacturer_websites'] and vendor:
                all_results.extend(self.search_manufacturer_website(title, vendor, 3))
                time.sleep(self.config['search_settings']['delay_between_requests'])
        
        # Remove duplicates and prioritize high-resolution images
        unique_results = []
        seen_urls = set()
        
        for result in all_results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                # Check if it's high resolution
                if self.is_high_resolution(result.url):
                    result.confidence += 0.2  # Boost confidence for high-res images
                unique_results.append(result)
        
        # Sort by confidence (highest first), then by resolution
        unique_results.sort(key=lambda x: (x.confidence, self.is_high_resolution(x.url)), reverse=True)
        
        return unique_results[:15]  # Return top 15 results for better selection
    
    def process_csv(self, input_file: str, output_file: str = None):
        """Process the CSV file and scrape images for each product"""
        if output_file is None:
            output_cfg = self.config.get('output_settings', {})
            base_name = output_cfg.get('output_filename')
            if not base_name:
                # derive from input name
                base_name = os.path.basename(input_file).replace('.csv', '_with_images.csv')

            # add timestamp if enabled
            add_ts = bool(output_cfg.get('add_timestamp', False))
            if add_ts:
                from datetime import datetime
                ts_fmt = output_cfg.get('timestamp_format', '%Y-%m-%d-%H%M')
                name, ext = os.path.splitext(base_name)
                base_name = f"{name}_{datetime.now().strftime(ts_fmt)}{ext}"

            # prepend output directory if provided
            output_dir = output_cfg.get('output_dir')
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, base_name)
            else:
                output_file = base_name
        
        # Backup original file
        if self.config['output_settings']['backup_original_csv']:
            backup_file = input_file.replace('.csv', '_backup.csv')
            import shutil
            shutil.copy2(input_file, backup_file)
            logger.info(f"Backup created: {backup_file}")
        
        # Read CSV
        products = []
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            products = list(reader)
        
        # Apply test mode limit if enabled
        if self.config['search_settings'].get('test_mode', False):
            test_limit = self.config['search_settings'].get('test_limit', 200)
            products = products[:test_limit]
            logger.info(f"TEST MODE: Processing only first {len(products)} products")
        
        # Determine resume position
        start_index = 1
        ckpt = self.load_checkpoint()
        if ckpt and ckpt.get('input_file') == input_file:
            last_index = int(ckpt.get('last_index', 0))
            if last_index >= 1:
                start_index = last_index + 1
                logger.info(f"RESUME: Continuing from product index {start_index}")

        logger.info(f"Processing {len(products)} products (starting at index {start_index})...")
        
        # Process each product
        for i, product in enumerate(products, 1):
            if i < start_index:
                continue
            logger.info(f"Processing product {i}/{len(products)}: {product.get('Title', 'Unknown')}")
            
            # Skip if already has image
            if product.get('Image Src') and product.get('Image Src').strip():
                logger.info("Product already has image, skipping...")
                continue
            
            # Search for images
            search_results = self.search_product_images(product)
            
            if search_results:
                # Get the best result (prioritize high-resolution)
                best_result = search_results[0]
                
                # Try to find an even better high-resolution image
                for result in search_results[:5]:  # Check top 5 results
                    if self.is_high_resolution(result.url) and not self.is_high_resolution(best_result.url):
                        best_result = result
                        break
                
                product['Image Src'] = best_result.url
                product['Image Alt Text'] = best_result.title
                
                # Add resolution info to log
                resolution_info = ""
                if self.is_high_resolution(best_result.url):
                    resolution_info = " (HIGH-RES)"
                
                logger.info(f"Found image URL: {best_result.url} from {best_result.source}{resolution_info}")
                self.downloaded_count += 1
            else:
                logger.warning("No images found for this product")
                self.failed_count += 1
            
            # Save progress and checkpoint every N products
            save_interval = int(self.checkpoint_cfg.get('every_n_products', 20))
            if i % save_interval == 0:
                self.save_progress(products, output_file)
                self.save_checkpoint({
                    'input_file': input_file,
                    'output_file': output_file,
                    'last_index': i,
                    'timestamp': int(time.time())
                })
                logger.info(f"Progress saved: {i} products processed")
        
        # Save final results
        self.save_progress(products, output_file)
        # Clear checkpoint on success
        self.clear_checkpoint()
        
        logger.info(f"Scraping completed!")
        logger.info(f"Total products processed: {len(products)}")
        logger.info(f"Images found: {self.downloaded_count}")
        logger.info(f"Failed searches: {self.failed_count}")
        logger.info(f"Results saved to: {output_file}")
    
    def save_progress(self, products: List[Dict], output_file: str):
        """Save current progress to CSV file"""
        if not products:
            return
            
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = products[0].keys()
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(products)

def main():
    """Main function to run the image scraper"""
    print("🖼️  Smith Pharmacy Image Scraper")
    print("=" * 50)
    
    # Initialize scraper
    scraper = ImageScraper()
    
    # Get input file
    input_file = "dataset/Full missing image product list.csv"
    
    if not os.path.exists(input_file):
        print(f"❌ Error: Input file not found: {input_file}")
        return
    
    print(f"📁 Input file: {input_file}")
    print(f"⚙️  Configuration loaded from: scraper_config.json")
    
    # Show test mode status
    if scraper.config['search_settings'].get('test_mode', False):
        test_limit = scraper.config['search_settings'].get('test_limit', 200)
        print(f"🧪 TEST MODE: Processing only first {test_limit} products")
    
    print(f"📊 Search sources enabled:")
    for source, enabled in scraper.config['search_sources'].items():
        status = "✅" if enabled else "❌"
        print(f"   {status} {source.replace('_', ' ').title()}")
    
    print(f"💾 Save images locally: {'✅' if scraper.config['output_settings']['save_images_locally'] else '❌'}")
    print(f"📄 Output file: {scraper.config['output_settings'].get('output_filename', 'auto-generated')}")
    
    print("\n🚀 Starting image scraping...")
    print("=" * 50)
    
    try:
        scraper.process_csv(input_file)
        print("\n✅ Scraping completed successfully!")
    except KeyboardInterrupt:
        print("\n⏹️  Scraping interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during scraping: {e}")
        logger.error(f"Fatal error: {e}", exc_info=True)

if __name__ == "__main__":
    main()
