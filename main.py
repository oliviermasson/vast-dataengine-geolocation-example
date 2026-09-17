import boto3
import exifread
import pyarrow as pa
import vastdb
from io import BytesIO
from datetime import datetime
from opentelemetry import trace
import json
import os

from geolocation import resolve_location, format_location

version="v1.19"

SECRETS_DIR = "/secrets"

def read_secret(name):
    # Credentials come from a DataEngine pipeline secret, mounted as files under
    # /secrets (flat, or nested one level under the secret's own name — mount
    # layout isn't documented, so both are checked). Falls back to the
    # environment for backward compatibility with plain env-var configuration.
    flat_path = os.path.join(SECRETS_DIR, name)
    if os.path.isfile(flat_path):
        with open(flat_path) as f:
            return f.read().strip()

    if os.path.isdir(SECRETS_DIR):
        for entry in os.scandir(SECRETS_DIR):
            if entry.is_dir():
                nested_path = os.path.join(entry.path, name)
                if os.path.isfile(nested_path):
                    with open(nested_path) as f:
                        return f.read().strip()

    return os.environ[name]

def init(ctx):
    # Initialize s3 client
    access_key = read_secret('AWS_ACCESS_KEY_ID')
    secret_key = read_secret('AWS_SECRET_ACCESS_KEY')
    endpoint = os.environ['S3_ENDPOINT_URL']

    ctx.s3_client = boto3.client(
        's3',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
    )

    # Initialize VastDB session
    vastdb_endpoint = os.environ['VASTDB_ENDPOINT']
    vastdb_access_key = read_secret('VASTDB_ACCESS_KEY')
    vastdb_secret_key = read_secret('VASTDB_SECRET_KEY')

    ctx.vastdb_session = vastdb.connect(
        endpoint=vastdb_endpoint,
        access=vastdb_access_key,
        secret=vastdb_secret_key,
    )
    ctx.vastdb_bucket = os.environ.get('VASTDB_BUCKET', 'geoloc')
    ctx.vastdb_schema = os.environ.get('VASTDB_SCHEMA', 'omgeoloc')
    ctx.vastdb_table = os.environ.get('VASTDB_TABLE', 'geoloc')

    ctx.logger.info("=====================================================================================================")
    ctx.logger.info(f"✅ Initialized successfully {version}")

def handler(ctx, event):
    # Events Processing comes here
    ctx.logger.info("----------------------------------------------------------------------")
    ctx.logger.info(f"{version} Handler received following event : {event}")

    image_data = get_image_from_s3(ctx, event)
    if image_data is None:
        ctx.logger.warning("⚠️  WARNING image cannot be read from S3")
        ctx.logger.info("----------------------------------------------------------------------")
        return {
            "bucket": "",
            "key": "",
            "summary": "❌ EXIF data not extracted because image data is None",
        }
    else:
        exif_data = extract_exif_data(ctx, image_data)

    with ctx.tracer.start_as_current_span("Proceed EXIF data extraction") as span:
        raw_tags = exif_data.get('_raw_tags', {})
        maker_parts = [str(raw_tags[k]) for k in ('Image Make', 'Image Model') if k in raw_tags]
        maker = " ".join(p.strip() for p in maker_parts if p.strip()) or None
        ctx.logger.info(f"Maker: {raw_tags.get('Image Make', 'N/A')} {raw_tags.get('Image Model', 'N/A')}")

        date_exif = raw_tags.get('EXIF DateTimeOriginal') or raw_tags.get('Image DateTime')
        ctx.logger.info(f"date_exif : {date_exif}")
        date_exif_date = None
        if date_exif:
            try:
                date_parsed = datetime.strptime(str(date_exif), '%Y:%m:%d %H:%M:%S')
                date_display = date_parsed.strftime('%Y-%m-%d')  # Format date32
                date_exif_date = date_parsed.date()
            except:
                date_display = str(date_exif)
        else:
            date_display = 'N/A'
        ctx.logger.info(f"Date: {date_display}")

        width = parse_int_tag(ctx, raw_tags.get('Image ImageWidth'))
        height = parse_int_tag(ctx, raw_tags.get('Image ImageLength'))
        ctx.logger.info(f"Dimensions: {width if width is not None else 'N/A'}x{height if height is not None else 'N/A'}")

        gps_lat = parse_gps_coordinate(ctx,
            raw_tags.get('GPS GPSLatitude'),
            raw_tags.get('GPS GPSLatitudeRef'),
            'Latitude'
        )
        gps_lon = parse_gps_coordinate(ctx,
            raw_tags.get('GPS GPSLongitude'),
            raw_tags.get('GPS GPSLongitudeRef'),
            'Longitude'
        )
        location = None
        if gps_lat is not None and gps_lon is not None:
            ctx.logger.info(f"  - GPS: {gps_lat:.6f}, {gps_lon:.6f}")
            location = resolve_location(ctx, gps_lat, gps_lon)
            if location:
                ctx.logger.info(f"  - Location: {format_location(location)}")
                ctx.logger.info(f"  - Nearest city: {location['nearest_city'] or 'N/A'} ({location['nearest_city_distance_km']} km)")
                ctx.logger.info(f"  - State/Region: {location['state'] or 'N/A'}")
                ctx.logger.info(f"  - Country: {location['country'] or 'N/A'} ({location['country_code'] or 'N/A'})")
                ctx.logger.info(f"  - Continent: {location['continent'] or 'N/A'}")
        else:
            ctx.logger.info("  - GPS: N/A (no GPS coordinates in EXIF data)")

        location_str = format_location(location) if location else None
        city = location["city"] if location else None
        region = location["state"] if location else None
        country = location["country"] if location else None
        continent = location["continent"] if location else None

        source_photo = f"s3://{event.bucket}/{event.object_key}"
        store_photo_metadata(
            ctx,
            source_photo=source_photo,
            maker=maker,
            date_exif=date_exif_date,
            width=width,
            height=height,
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            location_str=location_str,
            city=city,
            region=region,
            country=country,
            continent=continent,
        )

        trace.get_current_span().set_attributes({
            "Event.ID": event.id,
            "Event.Type": event.type,
            "Event.Subtype": event.subtype,
        })
        ctx.logger.info("=====================================================================================================")
        return {
            "bucket": event.bucket,
            "key": event.object_key,
            "summary": "✅ EXIF data extracted successfully from image",
            "latitude": gps_lat,
            "longitude": gps_lon,
            "city": location["city"] if location else None,
            "state": location["state"] if location else None,
            "country": location["country"] if location else None,
            "country_code": location["country_code"] if location else None,
            "continent": location["continent"] if location else None,
        }

def get_image_from_s3(ctx, event):
    # If image uploaded, read image from S3
    ctx.logger.info("Inside get_image_from_s3 function...")
    if(event.bucket is None or event.object_key is None):
        # troublshooting only if bucket or object key is None
        ctx.logger.info("📋 Event attributes:")
        for attr in dir(event):
            if not attr.startswith('_'):
                try:
                    value = getattr(event, attr)
                    if not callable(value):
                        ctx.logger.info(f"  {attr}: {value}")
                except:
                    pass
        ctx.logger.error("⚠️  ERROR bucket or object key is None")
        return None
    else:
        ctx.logger.info("Bucket and object_key retreived from event")
        ctx.logger.info(f"get_image_from_s3 Bucket : {event.bucket}")
        ctx.logger.info(f"get_image_from_s3 Object_key : {event.object_key}")

    with ctx.tracer.start_as_current_span("Get Image from S3") as span:
        try:
            response = ctx.s3_client.get_object(Bucket=event.bucket, Key=event.object_key)
            span.set_attributes({
                "Bucket": event.bucket,
                "ObjectKey": event.object_key,
            })
            image_data = response['Body'].read()
            return image_data
        except boto3.exceptions.Boto3Error as e:
            ctx.logger.error(f"⚠️  ERROR AWS S3: {e}")
            ctx.logger.info("----------------------------------------------------------------------")
            raise
        except Exception as e:
            ctx.logger.error(f"⚠️  ERROR retreiving image from S3: {e}")
            ctx.logger.info("----------------------------------------------------------------------")
            raise

def extract_exif_data(ctx, image_data):
    # Extract EXIF data from image
    ctx.logger.info("Inside extract_exif_data function...")
    with ctx.tracer.start_as_current_span("Extract EXIF data") as span:

        exif_data = {}

        try:
            tags = exifread.process_file(BytesIO(image_data), details=True)

            if not tags:
                ctx.logger.error("⚠️  ERROR not EXIF data found in image")
                ctx.logger.info("----------------------------------------------------------------------")
                raise

            for tag, value in tags.items():
                if tag.startswith('MakerNote'):
                    continue

                simple_tag = tag.split(' ')[-1] if ' ' in tag else tag

                if hasattr(value, 'values'):
                    exif_data[simple_tag] = value.values
                else:
                    exif_data[simple_tag] = str(value)

            exif_data['_raw_tags'] = tags

        except Exception as e:
            ctx.logger.error(f"⚠️  ERROR extracting EXIF data: {e}")
            ctx.logger.info("----------------------------------------------------------------------")
            raise
        return exif_data

def parse_gps_coordinate(ctx,gps_data, ref, which_coordinate):
    # Convert GPS coordinates to decimal format
    with ctx.tracer.start_as_current_span(f"Parse {which_coordinate} GPS coordinates") as span:
        if not gps_data or not ref:
                return None

        try:
            if hasattr(gps_data, 'values'):
                gps_data = gps_data.values

            def to_float(val):
                if hasattr(val, 'num') and hasattr(val, 'den'):
                        return float(val.num) / float(val.den) if val.den != 0 else 0
                return float(val)

            degrees = to_float(gps_data[0])
            minutes = to_float(gps_data[1])
            seconds = to_float(gps_data[2])

            decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)

            ref_str = str(ref.values[0] if hasattr(ref, 'values') else ref)
            if ref_str in ['S', 'W']:
                decimal = -decimal

            return decimal
        except Exception as e:
            ctx.logger.error(f"⚠️  ERROR parsing GPS coordinates: {e}")
            ctx.logger.info("----------------------------------------------------------------------")
            return None

def parse_int_tag(ctx, tag_value):
    # Convert an exifread tag (possibly a Ratio) to a plain int
    if tag_value is None:
        return None

    try:
        raw = tag_value.values[0] if hasattr(tag_value, 'values') else tag_value

        if hasattr(raw, 'num') and hasattr(raw, 'den'):
            return int(raw.num / raw.den) if raw.den != 0 else None

        return int(raw)
    except Exception as e:
        ctx.logger.error(f"⚠️  ERROR parsing integer EXIF tag: {e}")
        return None

def store_photo_metadata(ctx, source_photo, maker, date_exif, width, height,
                          gps_lat, gps_lon, location_str, city, region, country, continent):
    # Insert the photo metadata into VastDB, skipping it if source_photo is already stored
    with ctx.tracer.start_as_current_span("Store metadata in VastDB") as span:
        span.set_attributes({"SourcePhoto": source_photo})
        try:
            with ctx.vastdb_session.transaction() as tx:
                bucket = tx.bucket(ctx.vastdb_bucket)
                schema = bucket.schema(ctx.vastdb_schema)
                table = schema.table(ctx.vastdb_table)

                reader = table.select(
                    columns=['source_photo'],
                    predicate=(table['source_photo'] == source_photo),
                )
                existing = reader.read_all()

                if existing.num_rows > 0:
                    ctx.logger.info(f"ℹ️  Photo already present in VastDB, skipping insert: {source_photo}")
                    return False

                row = pa.table({
                    'source_photo': pa.array([source_photo], type=pa.string()),
                    'maker': pa.array([maker], type=pa.string()),
                    'date_exif': pa.array([date_exif], type=pa.date32()),
                    'width': pa.array([width], type=pa.int32()),
                    'height': pa.array([height], type=pa.int32()),
                    'gps_lat': pa.array([gps_lat], type=pa.float64()),
                    'gps_lon': pa.array([gps_lon], type=pa.float64()),
                    'location': pa.array([location_str], type=pa.string()),
                    'city': pa.array([city], type=pa.string()),
                    'region': pa.array([region], type=pa.string()),
                    'country': pa.array([country], type=pa.string()),
                    'continent': pa.array([continent], type=pa.string()),
                })
                table.insert(row)
                ctx.logger.info(f"✅ Photo metadata stored in VastDB: {source_photo}")
                return True
        except Exception as e:
            ctx.logger.error(f"⚠️  ERROR storing metadata in VastDB: {e}")
            return False
