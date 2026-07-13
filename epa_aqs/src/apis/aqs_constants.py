"""
EPA Air Quality System (AQS) API Constants

This module contains parameter codes for criteria pollutants, NAAQS standards,
and API configuration for the EPA Air Quality System.

Reference:
- API Documentation: https://aqs.epa.gov/aqsweb/documents/data_api.html
- Parameter Codes: https://aqs.epa.gov/aqsweb/documents/codetables/parameters.html
- NAAQS Standards: https://www.epa.gov/criteria-air-pollutants/naaqs-table
"""

# EPA AQS API Base URL
AQS_BASE_URL = "https://aqs.epa.gov/data/api"

# Parallelization settings (tested against EPA AQS API)
# EPA officially allows 10 requests/minute, but in practice:
# - 3 concurrent requests causes frequent timeouts (API gets overwhelmed)
# - 2 concurrent requests works reliably (~1s per query)
# Tested: 2 concurrent reduced total time from ~190s to ~10s for 6 pollutants
MAX_CONCURRENT_REQUESTS = 2  # 2 concurrent - optimal balance of speed and reliability
RATE_LIMIT_SECONDS = 1.0  # 1s delay per request within semaphore

# Criteria Pollutant Parameter Codes
# These are the six criteria pollutants regulated under the Clean Air Act
CRITERIA_POLLUTANTS = {
    "PM2.5": {
        "code": "88101",  # PM2.5 - Local Conditions (most common)
        "name": "Fine Particulate Matter (PM2.5)",
        "units": "µg/m³",
        "description": "PM2.5 - Local Conditions",
    },
    "PM10": {
        "code": "85101",  # PM10 - LC
        "name": "Coarse Particulate Matter (PM10)",
        "units": "µg/m³",
        "description": "PM10 - Local Conditions",
    },
    "Ozone": {"code": "44201", "name": "Ozone (O3)", "units": "ppm", "description": "Ozone"},
    "NO2": {"code": "42602", "name": "Nitrogen Dioxide (NO2)", "units": "ppb", "description": "Nitrogen dioxide (NO2)"},
    "SO2": {"code": "42401", "name": "Sulfur Dioxide (SO2)", "units": "ppb", "description": "Sulfur dioxide"},
    "CO": {"code": "42101", "name": "Carbon Monoxide (CO)", "units": "ppm", "description": "Carbon monoxide"},
}

# Additional pollutant codes that may be useful
ADDITIONAL_POLLUTANTS = {
    "Lead": {"code": "12128", "name": "Lead (TSP)", "units": "µg/m³", "description": "Lead (TSP) STP"},
    "NO": {"code": "42601", "name": "Nitric Oxide (NO)", "units": "ppb", "description": "Nitric oxide (NO)"},
    "NOx": {
        "code": "42603",
        "name": "Nitrogen Oxides (NOx)",
        "units": "ppb",
        "description": "Oxides of nitrogen (NOx)",
    },
}

# National Ambient Air Quality Standards (NAAQS)
# Current as of 2023 - these are the federal standards for criteria pollutants
NAAQS_STANDARDS = {
    "PM2.5": {
        "annual": {
            "value": 9.0,  # Updated 2024 standard (previously 12.0)
            "units": "µg/m³",
            "averaging_time": "Annual Mean",
            "form": "3-year average of annual mean",
            "standard_year": 2024,
        },
        "daily": {
            "value": 35.0,
            "units": "µg/m³",
            "averaging_time": "24-hour",
            "form": "98th percentile, averaged over 3 years",
            "standard_year": 2012,
        },
    },
    "PM10": {
        "daily": {
            "value": 150.0,
            "units": "µg/m³",
            "averaging_time": "24-hour",
            "form": "Not to be exceeded more than once per year on average over 3 years",
            "standard_year": 2012,
        }
    },
    "Ozone": {
        "8-hour": {
            "value": 0.070,
            "units": "ppm",
            "averaging_time": "8-hour",
            "form": "Annual fourth-highest daily maximum 8-hour concentration, averaged over 3 years",
            "standard_year": 2015,
        }
    },
    "NO2": {
        "annual": {
            "value": 53,
            "units": "ppb",
            "averaging_time": "Annual Mean",
            "form": "Annual mean",
            "standard_year": 1971,
        },
        "1-hour": {
            "value": 100,
            "units": "ppb",
            "averaging_time": "1-hour",
            "form": "98th percentile of 1-hour daily maximum concentrations, averaged over 3 years",
            "standard_year": 2010,
        },
    },
    "SO2": {
        "1-hour": {
            "value": 75,
            "units": "ppb",
            "averaging_time": "1-hour",
            "form": "99th percentile of 1-hour daily maximum concentrations, averaged over 3 years",
            "standard_year": 2010,
        }
    },
    "CO": {
        "8-hour": {
            "value": 9,
            "units": "ppm",
            "averaging_time": "8-hour",
            "form": "Not to be exceeded more than once per year",
            "standard_year": 1971,
        },
        "1-hour": {
            "value": 35,
            "units": "ppm",
            "averaging_time": "1-hour",
            "form": "Not to be exceeded more than once per year",
            "standard_year": 1971,
        },
    },
    "Lead": {
        "3-month": {
            "value": 0.15,
            "units": "µg/m³",
            "averaging_time": "3-month",
            "form": "Not to be exceeded",
            "standard_year": 2008,
        }
    },
}

# EPA AQS API Endpoints
AQS_ENDPOINTS = {
    "monitors_by_box": f"{AQS_BASE_URL}/monitors/byBox",
    "annual_data_by_box": f"{AQS_BASE_URL}/annualData/byBox",
    "daily_data_by_box": f"{AQS_BASE_URL}/dailyData/byBox",
    "quarterly_data_by_box": f"{AQS_BASE_URL}/quarterlyData/byBox",
    "sample_data_by_box": f"{AQS_BASE_URL}/sampleData/byBox",
    "list_states": f"{AQS_BASE_URL}/list/states",
    "list_counties_by_state": f"{AQS_BASE_URL}/list/countiesByState",
    "list_parameters": f"{AQS_BASE_URL}/list/parametersByClass",
}

REQUEST_TIMEOUT_SECONDS = 30  # Reduced from 60s - faster retries on timeout


# Helper function to get all criteria pollutant codes
def get_criteria_pollutant_codes() -> dict[str, str]:
    """
    Get a dictionary mapping pollutant names to parameter codes.

    Returns:
        dict: Mapping of pollutant name to parameter code
    """
    return {name: info["code"] for name, info in CRITERIA_POLLUTANTS.items()}


def get_pollutant_name(code: str) -> str:
    """
    Get the pollutant name from a parameter code.

    Args:
        code: AQS parameter code

    Returns:
        str: Pollutant name or the code if not found
    """
    for name, info in {**CRITERIA_POLLUTANTS, **ADDITIONAL_POLLUTANTS}.items():
        if info["code"] == code:
            return name
    return code
