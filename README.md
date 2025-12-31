---
sdk: streamlit
title: Directional Trading Bot
python_version: '3.12'
---


# Fyers Trading Bot

This is a Streamlit-based trading bot that connects to the Fyers API and executes trades based on a configurable moving average crossover strategy.

## Features

-   Connects to the Fyers API v3.
-   Executes trades (Equity or Options) based on a moving average crossover strategy.
-   Configurable moving average periods, timeframe, and other trading parameters.
-   Trailing stop-loss based on a moving average.
-   User-friendly interface built with Streamlit.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Usage

1.  **Run the Streamlit application:**
    ```bash
    streamlit run app.py
    ```

2.  **Open the application in your browser.**

3.  **Enter your Fyers API credentials:**
    -   Client ID
    -   Secret Key
    -   Redirect URI

4.  **Generate an access token:**
    -   Click the "Generate Access Token" button.
    -   You will be redirected to the Fyers login page.
    -   After logging in, you will be redirected back to your redirect URI with an auth code in the URL.
    -   Copy the auth code and paste it into the "Auth Code" field in the application.
    -   Click the "Generate Access Token" button again.

5.  **Configure the trading parameters:**
    -   Ticker
    -   Timeframe
    -   Moving average periods
    -   Max trades
    -   Trade type (Equity or Options)
    -   Option type (Call or Put)
    -   Quantity
    -   Expiry date (for options)

6.  **Start the bot:**
    -   Click the "Start Bot" button.

7.  **Monitor the bot's activity:**
    -   The application will display the live price of the ticker and a table of executed trades.
