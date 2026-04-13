# 💰 US Wage & Purchasing Power Map 2026

An interactive county-level map of the United States that answers one question:
**"If I work this job, can I actually afford to live here?"**

Built with Plotly Dash, powered by real government and economic data.

---

## 🌐 Live Demo
[**View the App →**](https://us-wage-map.onrender.com)



## 🔍 What It Does

This app combines two authoritative public datasets to calculate **real purchasing power** by county:

```
Household Income  −  Cost of Living  =  Leftover Income (Purchasing Power)
```

Counties are color-coded on an interactive US map:
- 🔴 **Red** — wages don't cover cost of living
- 🟡 **Yellow** — break-even
- 🟢 **Green** — meaningful surplus

---

## 📊 Data Sources

| Source | Dataset | Coverage |
|---|---|---|
| [Economic Policy Institute](https://www.epi.org/resources/budget/) | Family Budget Calculator 2026 | 3,143 counties × 10 family types |
| [Bureau of Labor Statistics](https://www.bls.gov/oes/) | Occupational Employment & Wage Statistics | 30+ occupations, state & national level |

**EPI cost categories included:** Housing, Food, Transportation, Healthcare (incl. insurance premiums), Childcare, Taxes (federal + state + local + payroll), Other Necessities

---

## ✨ Features

### 🗺️ Interactive Map
- Pan, zoom, and hover over any US county
- Tooltip shows salary, cost of living, and leftover income
- Color scale anchored at $0 (break-even) so red/green are always meaningful

### 🎛️ Dynamic Controls
- **30+ occupations** from BLS — from fast food workers to physicians
- **10 family types** — 1 or 2 adults, 0–4 children
- **Salary source toggle** — state-level BLS, national median, or your own salary

### 💵 Salary & Income Overrides
- Enter your own annual salary
- Add a **partner's income** for two-income households
- See combined household income reflected instantly on the map

### 🏠 Cost of Living Adjustments
- Adjust any EPI cost category (housing, food, transport, healthcare, childcare, other)
- Useful if you know you can get cheaper rent or have lower transportation costs

### 🧾 Tax Override
- EPI already includes county-specific tax estimates
- Override with your own effective tax rate if you have significant deductions
- Pre-tax deductions automatically reduce your taxable base

### 📊 Deductions & Additional Expenses
**Pre-tax deductions** (reduce taxable income):
- 401k / 403b (2025 limit: $23,500)
- HSA contributions (2025 limit: $4,300 / $8,550 family)
- FSA contributions (2025 limit: $3,300)
- Traditional IRA (2025 limit: $7,000)
- Health insurance premium override

**Post-tax expenses** (added to cost of living):
- Student loan payments
- Life & disability insurance
- Roth IRA contributions
- Pet costs
- Additional savings goals

### 📈 Live Stats Bar
- Household income being used
- Cost adjustments applied
- % of counties affordable
- Median leftover income nationally
- Best and hardest county for your scenario

---

## 🚀 Run Locally

### 1. Clone the repo
```bash
git clone https://github.com/Parcher-Flores/US-Wage-Map.git
cd US-Wage-Map
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Make sure your folder looks like this
```
US-Wage-Map/
├── wage_map_app.py
├── fbc_data_2026.xlsx
├── requirements.txt
├── Procfile
└── assets/
    └── custom.css
```

### 4. Run the app
```bash
python wage_map_app.py
```

Then open **http://127.0.0.1:8050** in your browser.

---

## 🛠️ Built With

- [Plotly Dash](https://dash.plotly.com/) — interactive web app framework
- [Plotly Express](https://plotly.com/python/plotly-express/) — choropleth map
- [Pandas](https://pandas.pydata.org/) — data processing
- [Requests](https://requests.readthedocs.io/) — BLS API calls
- [Gunicorn](https://gunicorn.org/) — production server

---

## 📁 Project Structure

```
├── wage_map_app.py       # Main Dash application
├── fbc_data_2026.xlsx    # EPI Family Budget Calculator data
├── assets/
│   └── custom.css        # Custom dropdown & UI styling
├── requirements.txt      # Python dependencies
├── Procfile              # Render deployment config
└── README.md
```

---

## 🔑 BLS API

This app uses the [BLS Public Data API v2](https://www.bls.gov/developers/).
A free API key is required — register at [bls.gov/developers](https://www.bls.gov/developers/).
Add your key to the `BLS_API_KEY` variable at the top of `wage_map_app.py`.

---

## 👤 Author

**Parcher-Flores**
- GitHub: [@Parcher-Flores](https://github.com/Parcher-Flores)
- LinkedIn: www.linkedin.com/in/appf

---

*Salary data: BLS OES 2023–2024 estimates. Cost-of-living data: EPI 2026 edition in 2025 dollars.*
