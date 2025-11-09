import ee
import json
from typing import Dict, Any, List

# --- GEE Configuration ---

# Global flag to track GEE initialization status
GEE_INITIALIZED = False

# GEE Asset paths for analysis
ADMIN_BOUNDARIES_ASSET = "FAO/GAUL/2015/level1" # GAUL Level 1 (Provinces/Regions)
POPULATION_ASSET = "JRC/GHS/GHS_POP/GHS_POP_E2020_GLOBE_R2022A_54009_1000_V1_0" # 1km resolution
BUILDINGS_ASSET = "GOOGLE/Research/open-buildings/v3/polygons"
ROADS_ASSET = "OpenStreetMap/Global/2018/lines"

# Event-specific date ranges provided for Typhoon Kalmaegi (Tino)
EVENT_DATES = {
    "pre_start": '2025-10-25',
    "pre_end": '2025-10-30',
    "post_start": '2025-10-31',
    "post_end": '2025-11-10',
}

# --- GEE Core Functions ---

def initialize_gee():
    """
    Authenticates and initializes the Google Earth Engine API.
    
    This must be called before any GEE function is used.
    It relies on service account authentication configured in the Cloud Run environment.
    """
    global GEE_INITIALIZED
    if GEE_INITIALIZED:
        return

    try:
        # Initialize GEE using the service account credentials provided by Cloud Run.
        ee.Initialize()
        print("Google Earth Engine initialized successfully.")
        GEE_INITIALIZED = True
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to initialize GEE: {e}")
        raise RuntimeError("Failed to initialize Google Earth Engine. Check service account permissions.") from e

def _get_aoi_by_name(region_name: str) -> ee.Geometry:
    """
    Fetches the administrative boundary (AOI) from GEE based on the region name.
    """
    print(f"Fetching GEE administrative boundary for: {region_name}")
    
    # Map friendly names to the exact names in the GEE GAUL dataset
    region_map = {
        "Cebu Province, Philippines": "Cebu",
        "Gia Lai Province, Vietnam": "Gia Lai",
        "Northern Mindanao, Philippines": "Northern Mindanao" 
    }
    
    gee_region_name = region_map.get(region_name)
    if not gee_region_name:
        raise ValueError(f"Region name '{region_name}' is not mapped to a GEE administrative boundary.")

    # Find the feature in the GAUL dataset
    admin_collection = ee.FeatureCollection(ADMIN_BOUNDARIES_ASSET)
    aoi_feature = admin_collection.filter(ee.Filter.eq('ADM1_NAME', gee_region_name)).first()
    
    if not aoi_feature:
        raise Exception(f"Could not find GEE feature for '{gee_region_name}'.")

    return aoi_feature.geometry()

def fetch_geospatial_stats(region_name: str) -> Dict[str, Any]:
    """
    Executes the core Google Earth Engine analysis pipeline for a given region.
    
    This function performs real-time, server-side GEE computations to derive:
    1. Flood Extent (km²) using Sentinel-1 SAR.
    2. Affected Population (count) using JRC GHS-POP.
    3. Damaged Buildings (count) using Google Open Buildings.
    4. Critical Road Segments (GeoJSON) using OpenStreetMap.
    
    Args:
        region_name: The name of the region to analyze (e.g., "Cebu Province, Philippines").
        
    Returns:
        A dictionary of computed geospatial facts for the LLM agent.
    """
    initialize_gee()
    
    # 1. Get the AOI (Area of Interest) Geometry
    aoi_geometry = _get_aoi_by_name(region_name)
    
    # --- 2. Flood Extent Analysis (Sentinel-1 SAR) ---
    print("GEE: Starting Sentinel-1 flood extent analysis...")
    s1_collection = (ee.ImageCollection('COPERNICUS/S1_GRD')
                     .filterBounds(aoi_geometry)
                     .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                     .filter(ee.Filter.eq('instrumentMode', 'IW')))

    # Create pre- and post-event mosaics
    pre_event_img = s1_collection.filterDate(EVENT_DATES['pre_start'], EVENT_DATES['pre_end']).mean().clip(aoi_geometry)
    post_event_img = s1_collection.filterDate(EVENT_DATES['post_start'], EVENT_DATES['post_end']).mean().clip(aoi_geometry)

    # Simple thresholding for water (SAR values < -16 dB are likely water)
    pre_water = pre_event_img.select('VV').lt(-16)
    post_water = post_event_img.select('VV').lt(-16)
    
    # Identify new flood areas (water that exists now but didn't before)
    flooded_area_img = post_water.And(pre_water.Not())
    
    # Calculate the area of the flooded pixels in square kilometers
    flood_pixel_area = flooded_area_img.multiply(ee.Image.pixelArea()).divide(1_000_000) # 1e6
    flood_stats = flood_pixel_area.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi_geometry,
        scale=30, # Sentinel-1 resolution
        maxPixels=1e10
    )
    
    # .getInfo() pulls the server-side computation to the client (Cloud Run)
    flood_extent_km2 = flood_stats.get('VV').getInfo() or 0.0
    print(f"GEE: Calculated flood extent: {flood_extent_km2:.2f} km²")

    # --- 3. Affected Population Analysis (JRC GHS-POP) ---
    print("GEE: Analyzing affected population...")
    population_img = ee.Image(POPULATION_ASSET).clip(aoi_geometry)
    
    # Mask population by the flooded area
    affected_population_img = population_img.updateMask(flooded_area_img)
    
    population_stats = affected_population_img.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi_geometry,
        scale=1000, # Population data resolution
        maxPixels=1e10
    )
    affected_population = population_stats.get('population_count').getInfo() or 0
    print(f"GEE: Calculated affected population: {affected_population}")

    # --- 4. Damaged Buildings Analysis (Google Open Buildings) ---
    print("GEE: Analyzing damaged buildings...")
    buildings_collection = ee.FeatureCollection(BUILDINGS_ASSET).filterBounds(aoi_geometry)
    
    # Find buildings that intersect the flooded area
    flooded_buildings = buildings_collection.filterBounds(flooded_area_img.geometry())
    damaged_buildings_count = flooded_buildings.size().getInfo() or 0
    print(f"GEE: Calculated damaged buildings: {damaged_buildings_count}")

    # --- 5. Critical Road Segments Analysis (OpenStreetMap) ---
    print("GEE: Analyzing road network intersections...")
    roads_collection = ee.FeatureCollection(ROADS_ASSET).filterBounds(aoi_geometry)
    
    # Filter for major roads (primary, secondary, tertiary)
    major_roads = roads_collection.filter(ee.Filter.Or(
        ee.Filter.eq('highway', 'primary'),
        ee.Filter.eq('highway', 'secondary'),
        ee.Filter.eq('highway', 'tertiary')
    ))
    
    # Find road segments that intersect the flood area
    flooded_roads_features = major_roads.filterBounds(flooded_area_img.geometry())
    
    # Convert the flooded road geometries to a GeoJSON structure
    # This is the vector data output you requested
    flooded_roads_geojson = flooded_roads_features.geometry().getInfo()
    print(f"GEE: Identified {flooded_roads_features.size().getInfo()} major road segments in flooded zones.")

    # --- 6. Package Facts for the LLM Agent ---
    # The LLM receives the STATS and the road GeoJSON
    geospatial_facts = {
        "analysis_region": region_name,
        "flood_extent_km2": round(flood_extent_km2, 2),
        "affected_population_estimate": int(affected_population),
        "damaged_buildings_count": int(damaged_buildings_count),
        "critical_road_segments_geojson": flooded_roads_geojson, # Pass the vector data
        "weather_impact": "Analysis based on post-event satellite data. Weather conditions not included.",
        "aoi_geojson_layer": aoi_geometry.getInfo() # Send the AOI back for context
    }
    
    return geospatial_facts