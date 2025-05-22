from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import geopandas as gpd
from samgeo import SamGeo
import leafmap
import numpy as np
from sqlalchemy import create_engine

# ---------- CONFIGURATION ----------
DB_URL = "postgresql://postgres:Statsspeak@123@db.ounttrkvhnvhzfgtyklo.supabase.co:5432/postgres"  # Replace with actual creds
engine = create_engine(DB_URL)

app = Flask(__name__)
CORS(app)
sam = SamGeo(model_type="vit_h")

class BoundingBox:
    def __init__(self, min_lon, min_lat, max_lon, max_lat):
        self.min_lon = min_lon
        self.min_lat = min_lat
        self.max_lon = max_lon
        self.max_lat = max_lat

# ---------- SEGMENTATION LOGIC ----------
def run_segmentation(min_lon, min_lat, max_lon, max_lat):
    bbox = BoundingBox(min_lon, min_lat, max_lon, max_lat)
    coords = [bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat]

    image_file = "./data/satellite_image.tif"
    mask_file = "./data/masks.tif"
    vector_file = "./data/masks.geojson"

    os.makedirs("data", exist_ok=True)
    for f in [mask_file, vector_file]:
        if os.path.exists(f):
            os.remove(f)

    # Download image tile
    leafmap.tms_to_geotiff(
        output=image_file,
        bbox=coords,
        zoom=15,
        source="SATELLITE",
        overwrite=True
    )

    # Segment and vectorize
    sam.generate(image_file, output=mask_file, foreground=True, unique=True, points_per_batch=32)
    sam.tiff_to_vector(mask_file, vector_file)

    # Load vectors
    gdf = gpd.read_file(vector_file)
    gdf.set_crs(epsg=3857, inplace=True, allow_override=True)
    gdf = gdf.to_crs(epsg=4326)

    # Remove invalid and empty geometries
    gdf = gdf.replace([np.inf, -np.inf], np.nan).dropna()
    gdf = gdf[gdf['geometry'].is_valid]
    gdf = gdf[gdf['geometry'].notnull()]

    # Save to PostGIS
    gdf.to_postgis("segments", engine, if_exists="append", index=False)

    # Return as GeoJSON
    return json.loads(gdf.to_json())

# ---------- ROUTES ----------
@app.route('/segment', methods=['POST'])
def segment():
    try:
        data = request.get_json(force=True)
        bbox = data.get("bbox")
        if not bbox or len(bbox) != 4:
            return jsonify({"error": "Invalid or missing bbox"}), 400

        result = run_segmentation(*bbox)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- MAIN ----------
if __name__ == '__main__':
    app.run(debug=True)
