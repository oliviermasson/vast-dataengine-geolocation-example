import math
import os

try:
    import reverse_geocode
except ImportError:
    reverse_geocode = None

# GeoNames continent assignment per ISO 3166-1 alpha-2 country code.
# "EU" and "AP" are pseudo-codes used by the geocoding dataset for
# region-level (rather than country-level) entries.
_COUNTRIES_BY_CONTINENT = {
    "Africa": (
        "AO BF BI BJ BW CD CF CG CI CM CV DJ DZ EG EH ER ET GA GH GM GN GQ GW KE KM LR LS LY MA "
        "MG ML MR MU MW MZ NA NE NG RE RW SC SD SH SL SN SO SS ST SZ TD TG TN TZ UG YT ZA ZM ZW"
    ),
    "Antarctica": "AQ BV GS HM TF",
    "Asia": (
        "AE AF AM AP AZ BD BH BN BT CC CN GE HK ID IL IN IO IQ IR JO JP KG KH KP KR KW KZ LA LB "
        "LK MM MN MO MV MY NP OM PH PK PS QA SA SG SY TH TJ TM TR TW UZ VN YE"
    ),
    "Europe": (
        "AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES EU FI FO FR GB GG GI GR HR HU IE IM IS IT "
        "JE LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS RU SE SI SJ SK SM UA VA XK"
    ),
    "North America": (
        "AG AI AW BB BL BM BQ BS BZ CA CR CU CW DM DO GD GL GP GT HN HT JM KN KY LC MF MQ MS MX "
        "NI PA PM PR SV SX TC TT US VC VG VI"
    ),
    "Oceania": (
        "AS AU CK CX FJ FM GU KI MH MP NC NF NR NU NZ PF PG PN PW SB TK TL TO TV UM VU WF WS"
    ),
    "South America": "AR BO BR CL CO EC FK GF GY PE PY SR UY VE",
}

CONTINENT_BY_COUNTRY = {
    code: continent
    for continent, codes in _COUNTRIES_BY_CONTINENT.items()
    for code in codes.split()
}

# The dataset is point-based: over an ocean or a desert the "nearest city" can be
# hundreds of kilometres away, which makes it meaningless as a location label.
# Past the country threshold even the country is wrong, e.g. the closest known
# place to McMurdo (Antarctica) is in New Zealand, 3500 km away.
MAX_CITY_DISTANCE_KM = float(os.environ.get('GEO_MAX_CITY_DISTANCE_KM', '150'))
MAX_COUNTRY_DISTANCE_KM = float(os.environ.get('GEO_MAX_COUNTRY_DISTANCE_KM', '500'))

# 0 keeps the closest known place, a higher value skips hamlets in favour of
# towns big enough to be recognisable.
MIN_CITY_POPULATION = int(os.environ.get('GEO_MIN_CITY_POPULATION', '0'))

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    # Great-circle distance between two points, in kilometers
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def resolve_location(ctx, latitude, longitude):
    # Reverse geocode decimal GPS coordinates into a place description.
    # Returns None when the lookup is impossible, never raises, so that a
    # geocoding problem cannot fail the EXIF extraction as a whole.
    if latitude is None or longitude is None:
        return None

    if reverse_geocode is None:
        ctx.logger.warning("⚠️  WARNING reverse_geocode not installed, skipping location lookup")
        return None

    with ctx.tracer.start_as_current_span("Reverse geocode GPS coordinates") as span:
        try:
            match = reverse_geocode.get(
                (latitude, longitude),
                min_population=MIN_CITY_POPULATION,
            )
        except Exception as e:
            ctx.logger.error(f"⚠️  ERROR reverse geocoding {latitude}, {longitude}: {e}")
            return None

        country_code = match.get('country_code') or ''
        distance_km = haversine_km(
            latitude, longitude, match['latitude'], match['longitude']
        )

        location = {
            "latitude": latitude,
            "longitude": longitude,
            "city": match.get('city'),
            "county": match.get('county'),
            "state": match.get('state'),
            "country": match.get('country'),
            "country_code": country_code,
            "continent": CONTINENT_BY_COUNTRY.get(country_code),
            "nearest_city": match.get('city'),
            "nearest_city_distance_km": round(distance_km, 1),
        }

        if distance_km > MAX_CITY_DISTANCE_KM:
            ctx.logger.warning(
                f"⚠️  WARNING nearest known place ({match.get('city')}) is {distance_km:.0f} km "
                f"from the photo, city reported as unknown"
            )
            location["city"] = None
            location["county"] = None

        if distance_km > MAX_COUNTRY_DISTANCE_KM:
            ctx.logger.warning(
                "⚠️  WARNING coordinates are too remote to infer a country "
                "(sea, desert or polar region)"
            )
            location["state"] = None
            location["country"] = None
            location["country_code"] = None
            location["continent"] = None
        elif not location["continent"]:
            ctx.logger.warning(f"⚠️  WARNING unknown continent for country code '{country_code}'")

        span.set_attributes({
            "Location.City": location["city"] or "",
            "Location.State": location["state"] or "",
            "Location.Country": location["country"] or "",
            "Location.Continent": location["continent"] or "",
        })
        return location


def format_location(location):
    # Human readable "City, State, Country (Continent)" summary for the logs.
    # The state is dropped when it repeats the city, as in city-states.
    if not location:
        return "N/A"

    parts = [location.get("city")]
    if location.get("state") and location.get("state") != location.get("city"):
        parts.append(location["state"])
    parts.append(location.get("country"))

    summary = ", ".join(p for p in parts if p)
    if not summary:
        return (f"Unknown (nearest known place: {location.get('nearest_city')}, "
                f"{location.get('nearest_city_distance_km')} km away)")

    if location.get("continent"):
        summary = f"{summary} ({location['continent']})"
    return summary
