import logging
import json
# Removed 'import ee' - This function is now a pure mock.

# Configure logging
logger = logging.getLogger(__name__)

def fetch_geospatial_stats(region_name: str) -> dict:
    """
    MOCKED FUNCTION: Immediately returns a predefined, safe dictionary
    containing simulated geospatial analysis data and a valid GeoJSON AOI.

    This bypasses all Google Earth Engine initialization and runtime errors,
    guaranteeing a clean start for the rest of the workflow.
    
    Args:
        region_name: The name of the region being analyzed (used for context only).

    Returns:
        A dictionary containing the simulated geospatial analysis results.
    """
    logger.info(f"MOCK: Bypassing GEE analysis. Returning fixed data for '{region_name}'.")

    # Define a simple, valid GeoJSON Polygon for Cebu (approximate)
    mock_aoi_geojson = {
        "type": "Polygon",
        "coordinates": [
            [[123.3, 9.4], [124.0, 9.4], [124.0, 11.4], [123.3, 11.4], [123.3, 9.4]]
        ]
    }

    # This is the expected output payload structure for the Damage Analysis Agent
    mock_stats = {
        "analysis_region": region_name,
        "flood_extent_km2": 45.1, 
        "affected_population_estimate": 12500,
        "damaged_buildings_count": 210,
        "critical_road_segments_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [123.89, 10.31]},
                    "properties": {"damage": "Simulated severe road cut near Cebu City."}
                }
            ]
        },
        "weather_impact": "MOCKED DATA: Successful analysis using simulated satellite data.",
        "aoi_geojson_layer": mock_aoi_geojson
    }
    
    return mock_stats