# 🖼️ Smith Pharmacy Image Scraper

A comprehensive Python tool to automatically scrape product images from multiple sources for your Shopify product catalog. This tool searches Google Images, Bing Images, Amazon, and manufacturer websites to find high-quality product images for your 5,673+ products.

## ✨ Features

- **🆓 Completely Free** - No API costs or subscription fees
- **🔍 Multi-Source Search** - Google Images, Bing Images, Amazon, and manufacturer websites
- **🎯 Smart Matching** - Uses product title, vendor, and SKU for accurate results
- **⚡ Batch Processing** - Handles thousands of products efficiently
- **🛡️ Error Handling** - Robust error handling and retry mechanisms
- **📊 Progress Tracking** - Real-time progress updates and logging
- **💾 Local Storage** - Downloads images locally and updates CSV with URLs
- **🔧 Configurable** - Easy-to-modify settings for different needs

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the Scraper

```bash
python image_scraper.py
```

That's it! The scraper will:
- Read your `dataset/Full missing image product list.csv`
- Search for images for each product
- Download images to `scraped_images/` folder
- Update the CSV with image URLs
- Create a backup of your original file

## ⚙️ Configuration

Edit `scraper_config.json` to customize the scraper:

```json
{
    "search_sources": {
        "google_images": true,        // Search Google Images
        "bing_images": true,          // Search Bing Images  
        "amazon": true,               // Search Amazon
        "manufacturer_websites": true // Search brand websites
    },
    "search_settings": {
        "max_results_per_source": 5,  // Max results per source
        "delay_between_requests": 1.0, // Delay between requests (seconds)
        "max_retries": 3              // Max retry attempts
    },
    "output_settings": {
        "save_images_locally": true,  // Download images locally
        "images_folder": "scraped_images", // Local folder for images
        "backup_original_csv": true   // Create backup of original CSV
    }
}
```

## 📁 Output Files

After running, you'll get:

- `dataset/Full missing image product list_with_images.csv` - Updated CSV with image URLs
- `dataset/Full missing image product list_backup.csv` - Backup of original file
- `scraped_images/` - Folder containing downloaded images
- `scraper.log` - Detailed log file

## 🔍 How It Works

1. **Reads your CSV** - Loads the product list from Shopify export
2. **Creates search queries** - Combines product title, vendor, and SKU
3. **Searches multiple sources**:
   - Google Images (high-quality results)
   - Bing Images (alternative source)
   - Amazon (product-specific images)
   - Manufacturer websites (brand-specific images)
4. **Validates images** - Checks image accessibility and format
5. **Downloads best match** - Saves the highest confidence result
6. **Updates CSV** - Adds image URL to your product data

## 🎯 Search Strategy

The scraper uses multiple search queries per product:
- `"Product Title" + "Vendor"`
- `"Product Title" + "SKU"`
- `"Product Title"`
- `"Vendor" + "SKU"`

This ensures maximum coverage and accuracy.

## 📊 Expected Results

For your 5,673 products:
- **Success Rate**: 70-85% (typical for product image scraping)
- **Processing Time**: 2-4 hours (with 1-second delays)
- **Images Found**: 4,000-4,800 products
- **Storage**: ~500MB-1GB (depending on image sizes)

## 🛠️ Troubleshooting

### Common Issues

**"No images found"**
- Try adjusting search queries in the code
- Check if product names are too generic
- Verify internet connection

**"Rate limiting errors"**
- Increase `delay_between_requests` in config
- Reduce `max_results_per_source`

**"Download failures"**
- Check disk space
- Verify write permissions
- Some images may be protected

### Performance Tips

1. **Run during off-peak hours** - Better success rates
2. **Use stable internet** - Reduces connection errors
3. **Monitor logs** - Check `scraper.log` for issues
4. **Resume if interrupted** - The scraper saves progress every 100 products

## 🔒 Legal Considerations

- **Respect robots.txt** - The scraper follows web scraping best practices
- **Rate limiting** - Built-in delays prevent overwhelming servers
- **Image rights** - Ensure you have rights to use scraped images
- **Terms of service** - Check website terms before scraping

## 📈 Monitoring Progress

The scraper provides real-time updates:
```
Processing product 1/5673: AOR Cortisol Adapt 120caps
Searching for: AOR Cortisol Adapt 120caps AOR
Found image: https://example.com/image.jpg
Downloaded image: aor-cortisol-adapt-120caps_1.jpg
```

## 🆘 Support

If you encounter issues:
1. Check the `scraper.log` file for detailed error messages
2. Verify your CSV file format matches the expected structure
3. Ensure all dependencies are installed correctly
4. Try running with a smaller subset of products first

## 📝 License

This tool is provided as-is for educational and commercial use. Please ensure compliance with website terms of service and applicable laws.

---

**Happy Scraping! 🎉**