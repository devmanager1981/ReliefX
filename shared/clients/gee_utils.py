import ee
import json
import logging
import os
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- GEE Configuration ---
# Set these as environment variables in Cloud Run for production
GEE_FALLBACK_MODE = os.getenv("GEE_FALLBACK_MODE", "false").lower() == "true"
GEE_SIMULATION_DATA_PATH = os.getenv("GEE_SIMULATION_DATA_PATH", "shared/mock_gee_data.json")

# GEE Collection IDs - Customize as needed for your specific analysis
SENTINEL2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
# For flood mapping, often a specific dataset like JRC Global Surface Water or custom flood detection
# For simplicity here, we'll focus on just imagery, but you'd integrate real flood models.
# Example: https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_DB_MODIS_V1
# Example: https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_MONITOR_MGD_LF_V1

# --- GEE Initialization ---
# Initialize GEE once globally. In Cloud Run, it will run on instance startup.
try:
    ee.Initialize()
    logger.info("Google Earth Engine initialized successfully.")
except Exception as e:
    logger.critical(f"FATAL: Failed to initialize Google Earth Engine: {e}")
    # In a production environment, this might indicate an auth issue.
    # The application should ideally crash or enter a degraded mode if GEE is essential.

# --- Helper Function for GEE (moved from main) ---
def get_gee_image(aoi: ee.Geometry) -> ee.Image:
    """
    Fetches a cloud-free Sentinel-2 image for the given Area of Interest (AOI).
    """
    end_date = ee.Date(datetime.now().isoformat())
    # Look back 30 days for a suitable image
    start_date = end_date.advance(-30, 'day') 

    # Filter Sentinel-2 collection for the AOI and date range
    collection = ee.ImageCollection(SENTINEL2_COLLECTION) \
        .filterBounds(aoi) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)) # Less than 10% cloudy pixels

    # Get the least cloudy image within the collection
    image = collection.sort('CLOUDY_PIXEL_PERCENTAGE').first()

    if image is None:
        logger.warning(f"No suitable Sentinel-2 image found for AOI between {start_date.format().getInfo()} and {end_date.format().getInfo()}.")
        # Return an empty image or throw an error, depending on downstream needs
        return ee.Image([]) # Return an empty image if no data found

    logger.info(f"Selected image acquisition time: {ee.Date(image.get('system:time_start')).format().getInfo()}")
    return image.select(['B4', 'B3', 'B2']) # Return Visible bands

def detect_flood_extent(image: ee.Image, aoi: ee.Geometry) -> List[Dict[str, Any]]:
    """
    Placeholder for actual flood detection.
    In a real scenario, this would use a robust flood detection algorithm (e.g., NDWI,
    multi-temporal analysis, or existing flood datasets).
    For this PoC, it will generate a simplified mock representation for the LLM.
    """
    # This is a critical point for real GEE flood detection.
    # For a hackathon, we'll simulate a plausible output.
    
    # In a production system:
    # 1. Use a pre-trained flood model or a robust index like NDWI/MNDWI.
    #    e.g., `ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')`
    # 2. Thresholding on NDWI to classify water.
    # 3. Apply morphological operations (erosion/dilation) to clean up.
    # 4. Convert the resulting binary image to vectors (polygons).
    # 5. Calculate area, perimeter, etc.
    
    # For demonstration, let's assume a simplified flood polygon if the image is not empty
    if image.bandNames().getInfo(): # Check if the image has actual bands
        # Create a tiny mock flood polygon within the AOI's bounds
        bounds = aoi.bounds().getInfo()['coordinates'][0]
        # Calculate approximate center and a small offset
        center_lon = (bounds[0][0] + bounds[1][0]) / 2
        center_lat = (bounds[0][1] + bounds[2][1]) / 2
        
        # Create a small square around the center to represent a flood
        mock_flood_coords = [
            [center_lon - 0.001, center_lat - 0.001],
            [center_lon + 0.001, center_lat - 0.001],
            [center_lon + 0.001, center_lat + 0.001],
            [center_lon - 0.001, center_lat + 0.001],
            [center_lon - 0.001, center_lat - 0.001]
        ]
        
        # Create a dummy feature collection
        feature = ee.Feature(ee.Geometry.Polygon(mock_flood_coords, None, False), {'area_km2': 0.1})
        # Export as GeoJSON FeatureCollection
        try:
            # We can't directly get GeoJSON from EE.FeatureCollection.toJson() client-side easily
            # without a task. For simple PoC, we return a mock structure.
            return [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [mock_flood_coords]
                    },
                    "properties": {
                        "area_km2": 0.1,
                        "description": "Simulated small flood area for PoC."
                    }
                }
            ]
        except ee.EEException as e:
            logger.error(f"Failed to get flood vector data: {e}")
            return []
    return []

def detect_road_cuts(aoi: ee.Geometry) -> List[Dict[str, Any]]:
    """
    Placeholder for actual road cut detection using GEE.
    This would involve more advanced image analysis or leveraging road network datasets.
    For this PoC, it will return a mock point if no real detection is possible.
    """
    # This is also a critical point for real GEE analysis.
    # In a production system, you'd integrate road network data (e.g., OpenStreetMap)
    # and then use change detection or visual inspection/ML models on high-resolution imagery.
    
    # For demonstration, let's simulate a single road cut near the AOI center
    bounds = aoi.bounds().getInfo()['coordinates'][0]
    center_lon = (bounds[0][0] + bounds[1][0]) / 2
    center_lat = (bounds[0][1] + bounds[2][1]) / 2
    
    mock_road_cut_coords = [center_lon + 0.002, center_lat + 0.002]

    return [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": mock_road_cut_coords
            },
            "properties": {
                "description": "Simulated road blockage near primary access route.",
                "severity": "high"
            }
        }
    ]

def fetch_geospatial_stats(region_name: str, aoi_geojson: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetches real geospatial statistics from Google Earth Engine based on the AOI.
    Includes robust error handling and a structured fallback mechanism.
    """
    logger.info(f"Attempting to fetch geospatial stats for region: {region_name}")

    # Use a structured fallback if GEE_FALLBACK_MODE is enabled or a critical error occurs
    fallback_data: Dict[str, Any] = {
        "analysis_region": f"CRITICAL FALLBACK for {region_name} - GEE data unavailable.",
        "analysis_timestamp": datetime.now().isoformat(),
        "weather_conditions": "Unknown (GEE data unavailable)",
        "precipitation_mm_24h": "N/A",
        "flood_extent_geojson": [],
        "road_cuts_geojson": [],
        "affected_buildings_geojson": [], # New field for more detail
        "population_impacted": "N/A (estimate unavailable)"
    }

    if GEE_FALLBACK_MODE:
        logger.warning("GEE_FALLBACK_MODE is enabled. Returning structured fallback data.")
        # If a simulation data path is provided for fallback, try loading that
        if GEE_SIMULATION_DATA_PATH and os.path.exists(GEE_SIMULATION_DATA_PATH):
            try:
                with open(GEE_SIMULATION_DATA_PATH, 'r') as f:
                    sim_data = json.load(f)
                    # Merge with fallback, ensuring critical fields are consistent
                    fallback_data.update(sim_data)
                    fallback_data["analysis_region"] = f"FALLBACK - Loaded from: {GEE_SIMULATION_DATA_PATH}"
                    logger.info("Loaded simulation data for fallback.")
            except Exception as e:
                logger.error(f"Could not load simulation data for fallback: {e}")
        return fallback_data


    try:
        # Convert GeoJSON dictionary to ee.Geometry object
        aoi = ee.Geometry(aoi_geojson)
        
        # --- 1. Fetch relevant imagery ---
        image = get_gee_image(aoi)

        if not image.bandNames().getInfo(): # Check if get_gee_image returned an empty image
            logger.warning("No valid GEE image found for analysis. Using fallback.")
            return fallback_data

        # --- 2. Perform various analyses (using placeholders for now) ---
        
        # Flood Detection
        flood_extent = detect_flood_extent(image, aoi) # This