Arbitrage Betting Bot

A full-stack arbitrage betting system that scrapes odds across multiple sportsbooks, finds risk-free betting opportunities, and presents them on a modern dashboard.

Features

Integrates with The Odds API for live odds

Supports multiple sports (NFL, MLB, Soccer, Tennis, Cricket, etc.)

Filters out live games — only shows matches that haven’t started yet

Calculates guaranteed profit margin and betting plan

Displays both Decimal and American odds

React + Tailwind dashboard frontend

FastAPI + PostgreSQL backend with clean data models

Secure with .env file for API keys and DB credentials

Project Structure
arbitrage-bot/
│
├── backend/              # FastAPI backend
│   ├── db.py             # Database setup
│   ├── fetch_odds.py     # Fetch + store odds from API
│   ├── init_db.py        # Initialize database
│   ├── main.py           # FastAPI app & arbitrage logic
│   ├── models.py         # SQLAlchemy models
│   ├── requirements.txt  # Python dependencies
│   └── .env              # Your local secrets (not pushed to GitHub)
│
├── frontend/             # Frontend (React + Tailwind in HTML)
│   └── index.html        # Interactive dashboard
│
├── .gitignore            # Ignore secrets, venv, cache, etc.
├── README.md             # This file
└── useful.txt            # Notes/resources

Installation
1. Clone the repository
git clone https://github.com/your-username/arbitrage-bot.git
cd arbitrage-bot

2. Backend Setup
cd backend
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
 . .venv\Scripts\Activate.ps1

3. Setup PostgreSQL

Create a database:

CREATE DATABASE arbdb;
CREATE USER arbuser WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE arbdb TO arbuser;

4. Configure Environment

Create a .env file in /backend (not pushed to GitHub):

ODDS_API_KEY=your_api_key_here
DATABASE_URL=postgresql://arbuser:yourpassword@localhost:5432/arbdb

Usage
1. Initialize the database
python init_db.py

2. Fetch and store odds
python fetch_odds.py

3. Run the FastAPI server
uvicorn main:app --reload


API available at: http://127.0.0.1:8000/arbitrage

4. Open the Frontend

Open /frontend/index.html in your browser for the dashboard.

Supported Sportsbooks (Canada-focused)

DraftKings

FanDuel

BetRivers

BetMGM

theScore

Bet365

PointsBet

Caesars

Sports Interaction

BET99

LeoVegas

NorthStar Bets

PowerPlay

TonyBet

Security

Secrets are stored in .env (ignored by Git)

An .env.example can be provided to guide setup

Do not commit your real API keys or database passwords

Roadmap

Add more betting markets (totals, spreads)

Multi-sport filtering on frontend

Real-time odds refresh with WebSockets

Deploy backend to a cloud service