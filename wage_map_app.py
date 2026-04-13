"""
Real Wage & Purchasing Power Map (2026)
Compares BLS median salaries vs EPI Family Budget Calculator cost of living
by county, with interactive family type and occupation selectors.

Requirements:
    pip install dash plotly pandas requests openpyxl

Run:
    python wage_map_app.py
"""

import json
import time
import requests
import pandas as pd
from dash import Dash, dcc, html, Input, Output, State, callback_context
import plotly.express as px
import os
# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
BLS_API_KEY   = os.environ.get("BLS_API_KEY", "") # Insert your API Key here
BLS_URL       = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
FBC_FILE      = "fbc_data_2026.xlsx"
GEOJSON_URL   = (
    "https://raw.githubusercontent.com/plotly/datasets/master/"
    "geojson-counties-fips.json"
)

# BLS OES Series format for STATE-level medians (area type 04 = state)
# Series ID pattern: OES + ST + {state_fips:02d} + 0000000 + {occ_stripped} + 3
# Simpler: use national estimate for all counties in a state and merge by state FIPS
# We'll pull NATIONAL median by occupation (series OEUM000000000000XXX3)
# and state-level estimates where available.

# Occupation catalog  ──  SOC code : display label
OCCUPATIONS = {
    "00-0000": "All Occupations",
    "11-0000": "Management",
    "13-0000": "Business & Financial Operations",
    "15-0000": "Computer & Mathematical",
    "17-0000": "Architecture & Engineering",
    "19-0000": "Life, Physical & Social Science",
    "21-0000": "Community & Social Service",
    "23-0000": "Legal",
    "25-0000": "Educational Instruction & Library",
    "27-0000": "Arts, Design, Entertainment & Media",
    "29-0000": "Healthcare Practitioners & Technical",
    "31-0000": "Healthcare Support",
    "33-0000": "Protective Service",
    "35-0000": "Food Preparation & Serving",
    "37-0000": "Building & Grounds Cleaning",
    "39-0000": "Personal Care & Service",
    "41-0000": "Sales & Related",
    "43-0000": "Office & Administrative Support",
    "45-0000": "Farming, Fishing & Forestry",
    "47-0000": "Construction & Extraction",
    "49-0000": "Installation, Maintenance & Repair",
    "51-0000": "Production",
    "53-0000": "Transportation & Material Moving",
    # Selected detailed occupations
    "25-2021": "Elementary School Teachers",
    "25-2031": "Secondary School Teachers",
    "29-1141": "Registered Nurses",
    "29-1216": "General Internal Medicine Physicians",
    "15-1252": "Software Developers",
    "41-2031": "Retail Salespersons",
    "35-3023": "Fast Food & Counter Workers",
    "53-3032": "Heavy & Tractor-Trailer Truck Drivers",
    "33-3051": "Police & Sheriff's Patrol Officers",
    "11-1021": "General & Operations Managers",
}

# Family type labels
FAMILY_LABELS = {
    "1p0c": "1 Adult, No Children",
    "1p1c": "1 Adult, 1 Child",
    "1p2c": "1 Adult, 2 Children",
    "1p3c": "1 Adult, 3 Children",
    "1p4c": "1 Adult, 4 Children",
    "2p0c": "2 Adults, No Children",
    "2p1c": "2 Adults, 1 Child",
    "2p2c": "2 Adults, 2 Children",
    "2p3c": "2 Adults, 3 Children",
    "2p4c": "2 Adults, 4 Children",
}

# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────
def load_fbc_data(path: str = FBC_FILE) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="County", header=1)
    df = df.rename(columns={"Total.1": "Annual_Total_Cost"})
    df = df.rename(columns={"Taxes.1": "Annual_Tax"})
    df["county_fips"] = df["county_fips"].astype(str).str.zfill(5)
    df["state_fips"]  = df["county_fips"].str[:2]
    # Clean county name (strip state suffix for display)
    df["county_label"] = df["County"].str.replace(r"\s+(County|Parish|Borough|Census Area|city|Municipality)$",
                                                    "", regex=True, case=False)
    df = df.rename(columns={"Taxes.1": "Annual_Tax"})
    return df[["county_fips", "state_fips", "County", "county_label",
               "State abv.", "Family", "Annual_Total_Cost", "Annual_Tax", "median_family_income"]]


def build_oes_series_id(occ_code: str) -> str:
    """
    Build a BLS OES national series ID for median annual wage.
    Pattern: OE + U + 000000 + 0 + {occ_no_dash} + 3
    e.g. All Occupations (00-0000) → OEUM000000000000003  (national, all areas, annual median)
    BLS OES series structure:
        OE  = prefix
        U   = cross-industry
        M   = national (or state area code)
        000000 = industry (000000 = all)
        {occ_no_dash} = 6-char occupation
        3   = datatype 3 = median annual wage
    """
    occ_stripped = occ_code.replace("-", "")  # e.g. "000000"
    return f"OEUM000000000000{occ_stripped[:6]}3"


def fetch_national_median(occ_code: str) -> float | None:
    """Fetch national median annual wage for an occupation from BLS OES."""
    series_id = build_oes_series_id(occ_code)
    payload = {
        "seriesid": [series_id],
        "startyear": "2023",
        "endyear": "2024",
        "registrationkey": BLS_API_KEY,
    }
    try:
        resp = requests.post(
            BLS_URL,
            data=json.dumps(payload),
            headers={"Content-type": "application/json"},
            timeout=15,
        )
        data = resp.json()
        if data.get("status") != "REQUEST_SUCCEEDED":
            return None
        series_list = data.get("Results", {}).get("series", [])
        if not series_list:
            return None
        periods = series_list[0].get("data", [])
        if not periods:
            return None
        # BLS returns "annual" period as "M13" or "A01"
        annual = [p for p in periods if p.get("period") in ("M13", "A01")]
        if annual:
            return float(annual[0]["value"])
        # Fall back to latest period
        return float(periods[0]["value"])
    except Exception:
        return None


def fetch_state_medians(occ_code: str) -> dict[str, float]:
    """
    Fetch state-level median annual wages for an occupation.
    BLS OES State series: OES + ST + {st_fips:02d} + 0000000 + {occ}3
    We batch all 50 states + DC in one request (51 series IDs).
    """
    STATE_FIPS = [
        "01","02","04","05","06","08","09","10","11","12","13","15","16","17","18",
        "19","20","21","22","23","24","25","26","27","28","29","30","31","32","33",
        "34","35","36","37","38","39","40","41","42","44","45","46","47","48","49",
        "50","51","53","54","55","56",
    ]
    occ_stripped = occ_code.replace("-", "")
    # OES state series: OEUS{st_fips}0000000{occ}3
    series_ids = [f"OEUS{st}0000000{occ_stripped}3" for st in STATE_FIPS]

    payload = {
        "seriesid": series_ids,
        "startyear": "2023",
        "endyear": "2024",
        "registrationkey": BLS_API_KEY,
    }
    result: dict[str, float] = {}
    try:
        resp = requests.post(
            BLS_URL,
            data=json.dumps(payload),
            headers={"Content-type": "application/json"},
            timeout=20,
        )
        data = resp.json()
        if data.get("status") != "REQUEST_SUCCEEDED":
            return result
        for series in data.get("Results", {}).get("series", []):
            sid = series["seriesID"]
            # Extract state FIPS from position 4-5
            st_fips = sid[4:6]
            periods = series.get("data", [])
            annual = [p for p in periods if p.get("period") in ("M13", "A01")]
            if annual:
                result[st_fips] = float(annual[0]["value"])
            elif periods:
                result[st_fips] = float(periods[0]["value"])
    except Exception:
        pass
    return result


# Simple in-memory cache to avoid re-fetching on every callback
_salary_cache: dict[str, dict] = {}


def get_salaries(occ_code: str) -> dict:
    """
    Returns {"national": float, "state": {fips: float}}.
    Uses cache; falls back to national if state data unavailable.
    """
    if occ_code in _salary_cache:
        return _salary_cache[occ_code]

    national = fetch_national_median(occ_code)
    state    = fetch_state_medians(occ_code)
    out = {"national": national, "state": state}
    _salary_cache[occ_code] = out
    return out


# ─────────────────────────────────────────────
# APP LAYOUT
# ─────────────────────────────────────────────
print("Loading EPI Family Budget Calculator data …")
FBC_DF = load_fbc_data()
print(f"  {len(FBC_DF):,} rows loaded across {FBC_DF['county_fips'].nunique():,} counties.")

# ─────────────────────────────────────────────
# APP & HELPERS
# ─────────────────────────────────────────────
app = Dash(__name__, title="Wage vs. Cost of Living Map 2026", assets_folder="assets")
server = app.server # required for Render/gunicorn deployment

def deduction_row(row_label, input_id, placeholder, ded_type, tooltip=""):
    """Like override_row but with a PRE/POST badge and tooltip on hover."""
    badge_color = "#2a6496" if ded_type == "pre" else "#5a3e7a"
    badge_text  = "PRE-TAX" if ded_type == "pre" else "POST-TAX"
    return html.Div([
        html.Div([
            html.Span(badge_text, style={
                "fontSize": "0.62rem", "fontWeight": "800", "color": "#ffffff",
                "background": badge_color, "borderRadius": "3px",
                "padding": "1px 5px", "marginRight": "6px", "letterSpacing": "0.05em",
            }),
            html.Span(row_label, style={
                "fontSize": "0.85rem", "color": "#c0c8d8", "fontWeight": "600",
            }),
        ], style={"width": "210px", "flexShrink": 0}),
        dcc.Input(
            id=input_id, type="number", placeholder=placeholder,
            debounce=True, className="override-input",
            min=0, step=100,
        ),
        html.Span("ⓘ", title=tooltip, style={
            "fontSize": "0.9rem", "color": "#4a7fb5", "marginLeft": "8px",
            "cursor": "help", "userSelect": "none",
        }),
    ], style={"display": "flex", "alignItems": "center", "gap": "8px", "marginBottom": "10px"})



def label(text):
    return html.Div(text, className="ctrl-label")

def override_row(row_label, input_id, placeholder, tooltip=""):
    return html.Div([
        html.Div(row_label, style={
            "width": "160px", "fontSize": "0.85rem", "color": "#c0c8d8",
            "fontWeight": "600", "flexShrink": 0,
        }),
        dcc.Input(
            id=input_id, type="number", placeholder=placeholder,
            debounce=True, className="override-input",
            min=0, step=100,
        ),
        html.Div(tooltip, style={"fontSize": "0.75rem", "color": "#556070", "marginLeft": "10px"}),
    ], style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "10px"})

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "backgroundColor": "#0f1117", "color": "#e0e0e0",
           "minHeight": "100vh", "padding": "0"},
    children=[

        # ── Header ──────────────────────────────
        html.Div(
            style={"background": "linear-gradient(135deg,#1a1f2e 0%,#252d42 100%)",
                   "padding": "24px 32px", "borderBottom": "1px solid #2a3349"},
            children=[
                html.H1("💰 Real Purchasing Power Map 2026",
                        style={"margin": 0, "fontSize": "1.8rem", "color": "#7eb8f7"}),
                html.P("County-level: BLS Median Salary − EPI Cost of Living = Leftover Income",
                       style={"margin": "6px 0 0", "color": "#8898aa", "fontSize": "0.9rem"}),
            ],
        ),

        # ── Main Controls ────────────────────────
        html.Div(
            style={"display": "flex", "flexWrap": "wrap", "gap": "24px",
                   "padding": "18px 32px", "backgroundColor": "#141929",
                   "borderBottom": "1px solid #2a3349", "alignItems": "flex-end"},
            children=[
                # Occupation
                html.Div([
                    label("Occupation (BLS)"),
                    dcc.Dropdown(
                        id="occ-dropdown",
                        options=[{"label": v, "value": k} for k, v in OCCUPATIONS.items()],
                        value="00-0000",
                        clearable=False,
                        className="bold-dropdown",
                        style={
                            "width": "340px",
                            "color": "#000000",
                            "fontWeight": "800",
                        },
                    ),
                ]),

                # Family type
                html.Div([
                    label("Family Type (EPI Budget)"),
                    dcc.Dropdown(
                        id="family-dropdown",
                        options=[{"label": v, "value": k} for k, v in FAMILY_LABELS.items()],
                        value="2p2c",
                        clearable=False,
                        className="bold-dropdown",
                        style={
                            "width": "270px",
                            "color": "#000000",
                            "fontWeight": "800",
                        },
                    ),
                ]),

                # Salary source radio
                html.Div([
                    label("Salary Data Source"),
                    dcc.RadioItems(
                        id="salary-source",
                        options=[
                            {"label": "  State-level (BLS OES)", "value": "state"},
                            {"label": "  National median (BLS OES)", "value": "national"},
                            {"label": "  My salary (override)", "value": "override"},
                        ],
                        value="state",
                        inline=True,
                        inputStyle={"marginRight": "5px", "accentColor": "#7eb8f7",
                                    "width": "14px", "height": "14px"},
                        labelStyle={"marginRight": "20px", "color": "#ffffff",
                                    "fontWeight": "800", "fontSize": "0.92rem",
                                    "cursor": "pointer"},
                    ),
                ]),
            ],
        ),

        # ── Override / Adjustments Panel ─────────
        html.Div(className="override-panel", style={"margin": "12px 32px 0 32px"}, children=[
            # Collapsible header
            html.Div(
                id="override-toggle",
                className="override-panel-header",
                n_clicks=0,
                children=[
                    html.Span("⚙️", style={"fontSize": "1rem"}),
                    html.Span("Salary & Cost Overrides",
                              style={"fontWeight": "700", "fontSize": "0.95rem", "color": "#7eb8f7"}),
                    html.Span("▸ Click to expand",
                              id="override-toggle-hint",
                              style={"fontSize": "0.75rem", "color": "#556070", "marginLeft": "auto"}),
                ],
            ),
            # Panel body (hidden by default)
            html.Div(
                id="override-body",
                style={"display": "none", "padding": "18px 24px 14px"},
                children=[
                    html.Div(style={"display": "flex", "gap": "48px", "flexWrap": "wrap"}, children=[

                        # ── Salary override ──────────────
                        html.Div([
                            html.Div("💵 Income", style={
                                "fontSize": "0.8rem", "color": "#7eb8f7", "fontWeight": "700",
                                "textTransform": "uppercase", "letterSpacing": "0.08em",
                                "marginBottom": "12px",
                            }),
                            override_row("My Annual Salary ($)", "override-salary", "e.g. 75000",
                                         "Overrides BLS data when 'My salary' is selected above"),
                            override_row("Partner's Salary ($)", "override-partner", "e.g. 55000",
                                         "Added to total household income (both sources)"),
                            html.Div(id="household-income-display",
                                     style={"marginTop": "4px", "marginBottom": "8px",
                                            "fontSize": "0.8rem", "color": "#74c69d", "fontWeight": "700"}),
                            # Tax info callout
                            html.Div([
                                html.Span("ℹ️ ", style={"fontSize": "0.85rem"}),
                                html.Span(
                                    "EPI tax estimates are already baked into the COL figures below, "
                                    "calculated per family type and county (federal + state + local + payroll). "
                                    "They vary by location — e.g. TX counties average ~9% vs CA ~18% of total COL. "
                                    "Use the tax adjustment below if your effective rate differs.",
                                    style={"fontSize": "0.75rem", "color": "#8898aa", "lineHeight": "1.5"},
                                ),
                            ], style={"maxWidth": "320px", "marginTop": "8px",
                                      "padding": "8px 10px", "background": "#0f1117",
                                      "borderRadius": "5px", "border": "1px solid #2a3349"}),
                        ]),

                        # ── Cost adjustments ─────────────
                        html.Div([
                            html.Div("🏠 Annual Cost Adjustments  (± added to EPI baseline)",
                                     style={
                                         "fontSize": "0.8rem", "color": "#7eb8f7", "fontWeight": "700",
                                         "textTransform": "uppercase", "letterSpacing": "0.08em",
                                         "marginBottom": "12px",
                                     }),
                            html.Div(style={"display": "flex", "gap": "32px", "flexWrap": "wrap"}, children=[
                                html.Div([
                                    override_row("Housing adj. ($)", "adj-housing", "e.g. -3000",
                                                 "Negative = cheaper than EPI estimate"),
                                    override_row("Food adj. ($)", "adj-food", "e.g. -500"),
                                    override_row("Transport adj. ($)", "adj-transport", "e.g. 1200"),
                                ]),
                                html.Div([
                                    override_row("Healthcare adj. ($)", "adj-healthcare", "e.g. -800"),
                                    override_row("Childcare adj. ($)", "adj-childcare", "e.g. -2000"),
                                    override_row("Other adj. ($)", "adj-other", "e.g. 500"),
                                ]),
                            ]),
                        ]),

                        # ── Tax override ─────────────────
                        html.Div([
                            html.Div("🧾 Tax Override", style={
                                "fontSize": "0.8rem", "color": "#7eb8f7", "fontWeight": "700",
                                "textTransform": "uppercase", "letterSpacing": "0.08em",
                                "marginBottom": "12px",
                            }),
                            html.Div([
                                html.Span("ℹ️ ", style={"fontSize": "0.85rem"}),
                                html.Span(
                                    "EPI calculates taxes per county and family type. "
                                    "Override only if you have deductions, credits, or filing "
                                    "status that significantly changes your effective rate.",
                                    style={"fontSize": "0.75rem", "color": "#8898aa", "lineHeight": "1.5"},
                                ),
                            ], style={"maxWidth": "260px", "marginBottom": "12px",
                                      "padding": "8px 10px", "background": "#0f1117",
                                      "borderRadius": "5px", "border": "1px solid #2a3349"}),
                            html.Div([
                                html.Label("Replace EPI tax with my effective rate:",
                                           style={"fontSize": "0.82rem", "color": "#c0c8d8",
                                                  "fontWeight": "600", "display": "block",
                                                  "marginBottom": "6px"}),
                                html.Div([
                                    dcc.Input(
                                        id="override-tax-rate", type="number",
                                        placeholder="e.g. 22", min=0, max=60, step=0.5,
                                        debounce=True, className="override-input",
                                        style={"width": "90px"},
                                    ),
                                    html.Span(" %  of gross household income",
                                              style={"fontSize": "0.85rem", "color": "#c0c8d8",
                                                     "fontWeight": "600", "marginLeft": "8px"}),
                                ], style={"display": "flex", "alignItems": "center"}),
                                html.Div(id="tax-override-display",
                                         style={"marginTop": "6px", "fontSize": "0.78rem",
                                                "color": "#f4a261", "fontWeight": "600"}),
                            ]),
                        ]),
                    ]),

                    # ── Deductions section ────────────────
                    html.Div(style={"borderTop": "1px solid #2a3349", "marginTop": "18px",
                                    "paddingTop": "16px"}, children=[
                        html.Div("📊 Deductions & Additional Expenses",
                                 style={"fontSize": "0.8rem", "color": "#7eb8f7", "fontWeight": "700",
                                        "textTransform": "uppercase", "letterSpacing": "0.08em",
                                        "marginBottom": "4px"}),
                        html.Div("Pre-tax deductions reduce your taxable income. Post-tax expenses are added directly to your COL.",
                                 style={"fontSize": "0.75rem", "color": "#8898aa", "marginBottom": "14px"}),

                        html.Div(style={"display": "flex", "gap": "48px", "flexWrap": "wrap"}, children=[

                            # Pre-tax deductions column
                            html.Div([
                                html.Div("PRE-TAX DEDUCTIONS  (reduce taxable income)",
                                         style={"fontSize": "0.72rem", "color": "#a0b8d8",
                                                "fontWeight": "700", "letterSpacing": "0.07em",
                                                "marginBottom": "10px"}),
                                deduction_row(
                                    "401k / 403b ($)", "ded-401k", "e.g. 23000",
                                    "pre", "NOT in EPI — pure addition to your expenses. "
                                    "2025 IRS limit: $23,500. Reduces taxable income.",
                                ),
                                deduction_row(
                                    "HSA contrib. ($)", "ded-hsa", "e.g. 4150",
                                    "pre", "NOT in EPI. 2025 limits: $4,300 (self) / $8,550 (family). "
                                    "Reduces taxable income. Medical spending from HSA doesn't add to COL.",
                                ),
                                deduction_row(
                                    "FSA contrib. ($)", "ded-fsa", "e.g. 3200",
                                    "pre", "NOT in EPI. 2025 limit: $3,300. Reduces taxable income. "
                                    "Funds used for healthcare/childcare reduce those COL categories.",
                                ),
                                deduction_row(
                                    "Traditional IRA ($)", "ded-ira", "e.g. 7000",
                                    "pre", "NOT in EPI. 2025 limit: $7,000 ($8,000 if 50+). "
                                    "Reduces taxable income if eligible.",
                                ),
                                deduction_row(
                                    "Health ins. premium ($)", "ded-health-premium", "e.g. 6000",
                                    "pre", "EPI Healthcare (~$18k/yr median for 2p2c) ALREADY includes "
                                    "estimated premiums + out-of-pocket. Enter your actual annual "
                                    "premium here to override EPI's estimate via the Healthcare adj. above. "
                                    "Employer-paid portion is pre-tax; employee portion shown here.",
                                ),
                            ]),

                            # Post-tax expenses column
                            html.Div([
                                html.Div("POST-TAX EXPENSES  (added to cost of living)",
                                         style={"fontSize": "0.72rem", "color": "#a0b8d8",
                                                "fontWeight": "700", "letterSpacing": "0.07em",
                                                "marginBottom": "10px"}),
                                deduction_row(
                                    "Student loans ($)", "ded-student-loan", "e.g. 4800",
                                    "post", "NOT in EPI — add your annual payments here. "
                                    "Average borrower pays ~$400/mo ($4,800/yr).",
                                ),
                                deduction_row(
                                    "Life insurance ($)", "ded-life-ins", "e.g. 1200",
                                    "post", "NOT in EPI. Term life for a family typically "
                                    "$50–$150/mo. Added directly to your COL.",
                                ),
                                deduction_row(
                                    "Disability ins. ($)", "ded-disability", "e.g. 900",
                                    "post", "NOT in EPI. Short/long-term disability premiums "
                                    "not covered by employer. Added to COL.",
                                ),
                                deduction_row(
                                    "Roth IRA ($)", "ded-roth", "e.g. 7000",
                                    "post", "NOT in EPI. Post-tax retirement savings. "
                                    "2025 limit: $7,000 ($8,000 if 50+). Added to COL, "
                                    "no tax reduction.",
                                ),
                                deduction_row(
                                    "Pet costs ($)", "ded-pet", "e.g. 2000",
                                    "post", "EPI Other Necessities covers some pet costs but "
                                    "likely underestimates. Add the gap here. "
                                    "Average dog owner spends ~$2,000–$4,000/yr.",
                                ),
                                deduction_row(
                                    "Other savings ($)", "ded-savings", "e.g. 5000",
                                    "post", "Emergency fund, college savings (529), vacation fund, "
                                    "or any savings goal not covered above. Added to COL.",
                                ),
                            ]),
                        ]),

                        # Deductions total display
                        html.Div(id="deductions-display",
                                 style={"marginTop": "12px", "fontSize": "0.82rem",
                                        "color": "#f4a261", "fontWeight": "700"}),
                    ]),


                    html.Div(id="override-summary",
                             style={"marginTop": "12px", "fontSize": "0.8rem", "color": "#74c69d",
                                    "fontWeight": "600"}),

                    # Reset button
                    html.Button("↺ Reset All Overrides", id="reset-overrides", n_clicks=0,
                                style={
                                    "marginTop": "10px", "padding": "6px 16px",
                                    "background": "#1a2035", "border": "1px solid #4a7fb5",
                                    "color": "#7eb8f7", "borderRadius": "5px",
                                    "cursor": "pointer", "fontSize": "0.82rem", "fontWeight": "700",
                                }),
                ],
            ),
        ]),

        # ── Stats bar ───────────────────────────
        html.Div(
            id="stats-bar",
            style={"display": "flex", "gap": "32px", "padding": "12px 32px",
                   "backgroundColor": "#10141f", "borderBottom": "1px solid #2a3349",
                   "flexWrap": "wrap", "marginTop": "12px"},
        ),

        # ── Loading + Map ───────────────────────
        dcc.Loading(
            id="loading", type="dot", color="#7eb8f7",
            children=dcc.Graph(
                id="choropleth-map",
                config={"scrollZoom": True, "displayModeBar": True,
                        "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
                style={"height": "calc(100vh - 340px)", "minHeight": "480px"},
            ),
        ),

        # ── Footer ──────────────────────────────
        html.Div(
            style={"padding": "12px 32px", "backgroundColor": "#0d1117",
                   "borderTop": "1px solid #1e2535", "fontSize": "0.78rem", "color": "#556070"},
            children=[
                "Sources: ",
                html.A("EPI Family Budget Calculator 2026", href="https://www.epi.org/resources/budget/",
                       target="_blank", style={"color": "#5a8fc0"}),
                " · ",
                html.A("BLS Occupational Employment & Wage Statistics", href="https://www.bls.gov/oes/",
                       target="_blank", style={"color": "#5a8fc0"}),
                " · Salary data: 2023–2024 OES estimates. Cost-of-living data: 2025 dollars.",
            ],
        ),

        dcc.Store(id="salary-store"),
    ],
)


# ─────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────

# ── Toggle override panel ────────────────────
@app.callback(
    Output("override-body", "style"),
    Output("override-toggle-hint", "children"),
    Input("override-toggle", "n_clicks"),
    prevent_initial_call=False,
)
def toggle_override_panel(n):
    if n and n % 2 == 1:
        return {"display": "block", "padding": "18px 24px 14px"}, "▾ Click to collapse"
    return {"display": "none"}, "▸ Click to expand"


# ── Reset overrides ──────────────────────────
@app.callback(
    Output("override-salary", "value"),
    Output("override-partner", "value"),
    Output("override-tax-rate", "value"),
    Output("adj-housing", "value"),
    Output("adj-food", "value"),
    Output("adj-transport", "value"),
    Output("adj-healthcare", "value"),
    Output("adj-childcare", "value"),
    Output("adj-other", "value"),
    Output("ded-401k", "value"),
    Output("ded-hsa", "value"),
    Output("ded-fsa", "value"),
    Output("ded-ira", "value"),
    Output("ded-health-premium", "value"),
    Output("ded-student-loan", "value"),
    Output("ded-life-ins", "value"),
    Output("ded-disability", "value"),
    Output("ded-roth", "value"),
    Output("ded-pet", "value"),
    Output("ded-savings", "value"),
    Input("reset-overrides", "n_clicks"),
    prevent_initial_call=True,
)
def reset_overrides(_):
    return [None] * 20


# ── Fetch BLS salary ─────────────────────────
@app.callback(
    Output("salary-store", "data"),
    Input("occ-dropdown", "value"),
    prevent_initial_call=False,
)
def fetch_and_cache_salary(occ_code):
    return get_salaries(occ_code)


# ── Main map + stats update ──────────────────
@app.callback(
    Output("choropleth-map", "figure"),
    Output("stats-bar", "children"),
    Output("override-summary", "children"),
    Output("household-income-display", "children"),
    Output("tax-override-display", "children"),
    Output("deductions-display", "children"),
    Input("salary-store", "data"),
    Input("family-dropdown", "value"),
    Input("salary-source", "value"),
    Input("occ-dropdown", "value"),
    Input("override-salary", "value"),
    Input("override-partner", "value"),
    Input("override-tax-rate", "value"),
    Input("adj-housing", "value"),
    Input("adj-food", "value"),
    Input("adj-transport", "value"),
    Input("adj-healthcare", "value"),
    Input("adj-childcare", "value"),
    Input("adj-other", "value"),
    # Pre-tax deductions
    Input("ded-401k", "value"),
    Input("ded-hsa", "value"),
    Input("ded-fsa", "value"),
    Input("ded-ira", "value"),
    Input("ded-health-premium", "value"),
    # Post-tax expenses
    Input("ded-student-loan", "value"),
    Input("ded-life-ins", "value"),
    Input("ded-disability", "value"),
    Input("ded-roth", "value"),
    Input("ded-pet", "value"),
    Input("ded-savings", "value"),
)
def update_map(salary_data, family_type, salary_source, occ_code,
               override_salary, override_partner, override_tax_rate,
               adj_housing, adj_food, adj_transport,
               adj_healthcare, adj_childcare, adj_other,
               ded_401k, ded_hsa, ded_fsa, ded_ira, ded_health_premium,
               ded_student_loan, ded_life_ins, ded_disability, ded_roth,
               ded_pet, ded_savings):

    # ── Build filtered base ──────────────────
    filtered = FBC_DF[FBC_DF["Family"] == family_type].copy()

    # ── Apply cost adjustments ───────────────
    total_adj = sum(v for v in [adj_housing, adj_food, adj_transport,
                                 adj_healthcare, adj_childcare, adj_other]
                    if v is not None)
    filtered["Annual_Total_Cost"] = filtered["Annual_Total_Cost"] + total_adj

    adj_parts = []
    for name, val in [("Housing", adj_housing), ("Food", adj_food),
                      ("Transport", adj_transport), ("Healthcare", adj_healthcare),
                      ("Childcare", adj_childcare), ("Other", adj_other)]:
        if val is not None and val != 0:
            adj_parts.append(f"{name}: {'+' if val > 0 else ''}${val:,.0f}")

    # ── Process deductions ───────────────────
    # Pre-tax: reduce taxable income before tax calculation
    pretax_deductions = {
        "401k/403b":     ded_401k or 0,
        "HSA":           ded_hsa or 0,
        "FSA":           ded_fsa or 0,
        "Trad. IRA":     ded_ira or 0,
        "Health premium": ded_health_premium or 0,
    }
    total_pretax = sum(pretax_deductions.values())

    # Post-tax: added straight to COL
    posttax_expenses = {
        "Student loans":  ded_student_loan or 0,
        "Life insurance": ded_life_ins or 0,
        "Disability ins": ded_disability or 0,
        "Roth IRA":       ded_roth or 0,
        "Pet costs":      ded_pet or 0,
        "Other savings":  ded_savings or 0,
    }
    total_posttax = sum(posttax_expenses.values())

    # Post-tax expenses go directly into COL
    filtered["Annual_Total_Cost"] = filtered["Annual_Total_Cost"] + total_posttax

    # Pre-tax deductions are added to COL (they come out of income) BUT also
    # reduce the taxable base when using a custom tax rate. Handled below.
    filtered["Annual_Total_Cost"] = filtered["Annual_Total_Cost"] + total_pretax

    # ── Determine primary salary ─────────────
    national_salary = (salary_data or {}).get("national")
    state_salaries  = (salary_data or {}).get("state", {})
    salary_note     = ""

    if salary_source == "override" and override_salary:
        filtered["primary_salary"] = float(override_salary)
        salary_note = f"custom ${float(override_salary):,.0f}"
    elif salary_source == "state" and state_salaries:
        filtered["primary_salary"] = filtered["state_fips"].map(state_salaries)
        if national_salary:
            filtered["primary_salary"] = filtered["primary_salary"].fillna(national_salary)
        salary_note = "state-level BLS"
    elif national_salary:
        filtered["primary_salary"] = national_salary
        salary_note = "national BLS"
    else:
        filtered["primary_salary"] = filtered["median_family_income"]
        salary_note = "EPI median (fallback)"

    # ── Add partner income ───────────────────
    partner_income = float(override_partner) if override_partner else 0.0
    filtered["salary"] = filtered["primary_salary"] + partner_income

    # ── Apply tax override ───────────────────
    # EPI taxes are already baked into Annual_Total_Cost per county + family type.
    # If user provides their own effective rate, swap out EPI's estimate.
    # Pre-tax deductions (401k, HSA etc.) reduce the taxable base first.
    tax_display = ""
    if override_tax_rate is not None and float(override_tax_rate) > 0:
        rate = float(override_tax_rate)
        taxable_income = filtered["salary"] - total_pretax  # pre-tax deductions lower the base
        taxable_income = taxable_income.clip(lower=0)
        custom_tax = taxable_income * (rate / 100.0)
        filtered["Annual_Total_Cost"] = (
            filtered["Annual_Total_Cost"] - filtered["Annual_Tax"] + custom_tax
        )
        median_custom = taxable_income.median() * rate / 100
        pretax_note = (f" (taxable base reduced by ${total_pretax:,.0f} pre-tax deductions)"
                       if total_pretax > 0 else "")
        tax_display = (f"EPI county tax replaced with your {rate:.1f}% effective rate"
                       f"{pretax_note} → ≈ ${median_custom:,.0f}/yr at median income")

    # ── Purchasing power ─────────────────────
    filtered["Purchasing_Power"] = filtered["salary"] - filtered["Annual_Total_Cost"]
    filtered["affordable"] = filtered["Purchasing_Power"] >= 0

    pp = filtered["Purchasing_Power"]
    abs_max     = max(abs(pp.min()), abs(pp.max()), 1)
    color_range = [-abs_max, abs_max]

    # ── Choropleth ───────────────────────────
    fig = px.choropleth(
        filtered,
        locations="county_fips",
        geojson=GEOJSON_URL,
        featureidkey="id",
        color="Purchasing_Power",
        range_color=color_range,
        hover_name="County",
        hover_data={
            "county_fips":          False,
            "State abv.":           True,
            "salary":               ":$,.0f",
            "Annual_Total_Cost":    ":$,.0f",
            "Purchasing_Power":     ":$,.0f",
            "median_family_income": ":$,.0f",
        },
        labels={
            "salary":               "Household Income",
            "Annual_Total_Cost":    "Annual Cost of Living",
            "Purchasing_Power":     "Leftover Income",
            "median_family_income": "Median Family Income",
            "State abv.":           "State",
        },
        scope="usa",
        color_continuous_scale=[
            [0.0,  "#d62728"],
            [0.35, "#f4a261"],
            [0.5,  "#ffffbf"],
            [0.65, "#74c69d"],
            [1.0,  "#1a7a4a"],
        ],
        color_continuous_midpoint=0,
    )

    fig.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        geo=dict(bgcolor="#0f1117", lakecolor="#141929", landcolor="#1c2233",
                 showlakes=True, showcoastlines=False),
        coloraxis_colorbar=dict(
            title="Leftover<br>Income ($)", tickprefix="$", tickformat=",.0f",
            len=0.75, thickness=14, bgcolor="#141929", bordercolor="#2a3349",
            tickfont=dict(color="#c0c8d8"), titlefont=dict(color="#c0c8d8"),
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        font=dict(color="#e0e0e0"),
    )

    # ── Stats bar ────────────────────────────
    n_afford   = filtered["affordable"].sum()
    n_total    = len(filtered)
    pct_afford = n_afford / n_total * 100 if n_total else 0
    median_pp  = pp.median()
    best_row   = filtered.loc[pp.idxmax()]
    worst_row  = filtered.loc[pp.idxmin()]
    salary_val = filtered["salary"].median()

    def stat_card(lbl, val, color="#e0e0e0"):
        return html.Div([
            html.Div(lbl, style={"fontSize": "0.7rem", "color": "#8898aa",
                                  "textTransform": "uppercase", "letterSpacing": "0.07em"}),
            html.Div(val, style={"fontSize": "1.05rem", "fontWeight": "700",
                                  "color": color, "marginTop": "2px"}),
        ])

    partner_note = f" + partner ${partner_income:,.0f}" if partner_income > 0 else ""
    stats = [
        stat_card("Household Income",
                  f"${salary_val:,.0f}  ({salary_note}{partner_note})",
                  "#7eb8f7"),
        stat_card("Cost Adj. Applied",
                  f"${total_adj:+,.0f}" if total_adj != 0 else "None",
                  "#f4a261" if total_adj != 0 else "#8898aa"),
        stat_card("Counties Affordable",
                  f"{n_afford:,} / {n_total:,}  ({pct_afford:.0f}%)",
                  "#74c69d" if pct_afford > 50 else "#f4a261"),
        stat_card("Median Leftover Income",
                  f"${median_pp:+,.0f}",
                  "#74c69d" if median_pp >= 0 else "#d62728"),
        stat_card("Best County",
                  f"{best_row['County']}, {best_row['State abv.']}  (${best_row['Purchasing_Power']:+,.0f})",
                  "#74c69d"),
        stat_card("Hardest County",
                  f"{worst_row['County']}, {worst_row['State abv.']}  (${worst_row['Purchasing_Power']:+,.0f})",
                  "#d62728"),
    ]

    # ── Override summary ──────────────────────
    summary_parts = []
    if salary_source == "override" and override_salary:
        summary_parts.append(f"My salary: ${float(override_salary):,.0f}/yr")
    if partner_income > 0:
        primary_med = float(override_salary) if override_salary else filtered["primary_salary"].median()
        summary_parts.append(f"Partner: ${partner_income:,.0f}/yr  →  combined ${primary_med + partner_income:,.0f}/yr")
    if adj_parts:
        summary_parts.append("COL adj: " + " · ".join(adj_parts)
                              + f"  →  net {'+' if total_adj >= 0 else ''}${total_adj:,.0f}/yr")
    if override_tax_rate and float(override_tax_rate) > 0:
        summary_parts.append(f"Tax rate: {float(override_tax_rate):.1f}%")
    if total_pretax > 0:
        active_pretax = [f"{k}: ${v:,.0f}" for k, v in pretax_deductions.items() if v > 0]
        summary_parts.append(f"Pre-tax deductions: {' · '.join(active_pretax)}  →  -${total_pretax:,.0f} taxable income")
    if total_posttax > 0:
        active_posttax = [f"{k}: ${v:,.0f}" for k, v in posttax_expenses.items() if v > 0]
        summary_parts.append(f"Post-tax expenses: {' · '.join(active_posttax)}  →  +${total_posttax:,.0f} COL")

    override_text = ("  ✔  Active: " + "   |   ".join(summary_parts)
                     if summary_parts
                     else "No overrides active — using EPI baseline costs and BLS salary data.")

    # ── Household income display ──────────────
    if override_salary or partner_income > 0:
        primary = float(override_salary) if override_salary else filtered["primary_salary"].median()
        if partner_income > 0:
            hh_display = (f"🏠 ${primary:,.0f}  +  partner ${partner_income:,.0f}"
                          f"  =  ${primary + partner_income:,.0f} combined/yr")
        else:
            hh_display = f"Your salary: ${primary:,.0f}/yr"
    else:
        hh_display = ""

    # ── Deductions display ────────────────────
    ded_parts = []
    if total_pretax > 0:
        ded_parts.append(f"Pre-tax: -${total_pretax:,.0f}/yr  "
                         f"({', '.join(k for k,v in pretax_deductions.items() if v > 0)})")
    if total_posttax > 0:
        ded_parts.append(f"Post-tax expenses: +${total_posttax:,.0f}/yr added to COL  "
                         f"({', '.join(k for k,v in posttax_expenses.items() if v > 0)})")
    deductions_display = "  |  ".join(ded_parts) if ded_parts else ""

    return fig, stats, override_text, hh_display, tax_display, deductions_display



# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\nStarting Dash server …")
    print("Open http://127.0.0.1:8050 in your browser.\n")
    app.run(debug=True, host="127.0.0.1", port=8050)
