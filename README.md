# Lighter Copy Trading System

A Python-based HTTP API service for executing copy trades on the Lighter platform.

## Features

- HTTP REST API for trade execution
- Multi-account support with account selection
- Symbol to market_id resolution
- Automatic position sizing based on reference ratios
- Stop loss management
- Telegram notifications
- Health monitoring and error handling
- Request queuing for concurrent requests

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `env.example` to `.env` and configure:
```bash
cp env.example .env
```

3. Edit `.env` with your configuration:
- Set `BASE_URL` and `L1_ADDRESS`
- Configure accounts in `ACCOUNTS` JSON array
- Set trading strategy parameters
- Configure Telegram bot API key and group ID
- Optionally set `API_KEY` for API authentication

## Configuration

### Environment Variables

- `BASE_URL`: Lighter API base URL
- `L1_ADDRESS`: Layer 1 address
- `ACCOUNTS`: JSON array of account configurations
- `MAX_SLIPPAGE`: Maximum acceptable slippage ratio (default: 0.01)
- `STOP_LOSS_RATIO`: Stop loss ratio (default: 0.05)
- `SCALING_FACTOR`: Position scaling factor (default: 0.8)
- `MAX_RETRIES`: Maximum retry attempts (default: 3)
- `RETRY_INTERVAL`: Retry interval in seconds (default: 5)
- `TELEGRAM_BOT_API_KEY`: Telegram bot API key
- `TELEGRAM_GROUP_ID`: Telegram group/chat ID
- `TELEGRAM_THREAD_ID`: (Optional) Thread ID for forum groups. Leave empty if not using forum groups
- `API_KEY`: Optional API key for authentication

## Usage

### Start the Server

```bash
python -m src.main
```

Or using uvicorn directly:
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### API Endpoints

#### POST /api/trade

Execute a trade request.

**Request Body:**
```json
{
  "account_index": 123,
  "market_id": 51,
  "trade_type": "long",
  "reference_position_ratio": 0.5
}
```

Or using symbol:
```json
{
  "account_index": 123,
  "symbol": "RESOLV",
  "trade_type": "long",
  "reference_position_ratio": 0.5
}
```

**Response:**
```json
{
  "status": "success",
  "message": "request accepted, processing in background",
  "request_id": "1234567890-abc123"
}
```

#### POST /api/trade/adjust

Adjust an existing position by increasing or decreasing it by a percentage.

**Request Body:**
```json
{
  "account_index": 123,
  "symbol": "RESOLV",
  "adjustment_type": "decrease",
  "percentage": 0.25
}
```

**Parameters:**
- `account_index` (integer, required): Account index to operate on
- `market_id` (integer, optional): Market ID of the position to adjust
- `symbol` (string, optional): Trading symbol of the position to adjust
- `adjustment_type` (string, required): `"increase"` to add to the position or `"decrease"` to reduce it
- `percentage` (float, required, 0-1): Portion of the current position to adjust (e.g., 0.25 = 25%)

Either `market_id` or `symbol` must be provided. The endpoint automatically determines the correct trade direction based on the current position. The same background queue, retry logic, and Telegram notifications apply.

**Response:**
```json
{
  "status": "success",
  "message": "adjustment request accepted, processing in background",
  "request_id": "1234567890-abc123"
}
```

#### GET /api/account/{account_index}

Get account information including balance, positions, and PnL.

**Path Parameters:**
- `account_index` (integer, required): Account index to query

**Response:**
```json
{
  "account_index": 281474976639902,
  "l1_address": "0xA52458D77266a7b8566D0CCE608a0eCC72229A60",
  "available_balance": "96.081014",
  "collateral": "100.005758",
  "total_asset_value": "99.844158",
  "cross_asset_value": "99.844158",
  "status": 0,
  "positions": [
    {
      "market_id": 51,
      "symbol": "RESOLV",
      "position": "80",
      "position_value": "11.290560",
      "avg_entry_price": "0.143152",
      "unrealized_pnl": "-0.161600",
      "realized_pnl": "0.000000",
      "sign": 1
    }
  ],
  "stop_loss_orders": [
    {
      "order_index": 12345,
      "order_id": "0xabc123...",
      "market_id": 51,
      "symbol": "RESOLV",
      "trigger_price": "0.135992",
      "price": null,
      "base_amount": "80",
      "remaining_base_amount": "80",
      "order_type": "stop-loss",
      "status": "active",
      "reduce_only": true
    }
  ]
}
```

**Response Fields:**
- `account_index`: Account index
- `l1_address`: Layer 1 address
- `available_balance`: Available balance in USDC
- `collateral`: Total collateral
- `total_asset_value`: Total asset value
- `cross_asset_value`: Cross asset value
- `status`: Account status (0 = inactive, 1 = active)
- `positions`: Array of position information
  - `market_id`: Market ID
  - `symbol`: Trading symbol
  - `position`: Position size
  - `position_value`: Position value in USDC
  - `avg_entry_price`: Average entry price
  - `unrealized_pnl`: Unrealized profit/loss
  - `realized_pnl`: Realized profit/loss
  - `sign`: Position direction (1 = long, -1 = short)
- `stop_loss_orders`: Array of stop loss order information
  - `order_index`: Order index
  - `order_id`: Order ID
  - `market_id`: Market ID
  - `symbol`: Trading symbol
  - `trigger_price`: Stop loss trigger price
  - `price`: Limit price (for stop-loss-limit orders, null for stop-loss orders)
  - `base_amount`: Initial base amount
  - `remaining_base_amount`: Remaining base amount
  - `order_type`: Order type ('stop-loss' or 'stop-loss-limit')
  - `status`: Order status
  - `reduce_only`: Whether the order is reduce-only

**Error Responses:**
- `404`: Account not found in configuration
- `500`: Failed to retrieve account information
- `503`: Lighter API is currently unavailable

#### GET /health

Check service health status.

**Response:**
```json
{
  "status": "healthy",
  "api_healthy": true
}
```

## Trade Types

- `long`: Open a long position
- `short`: Open a short position
- `close`: Close entire position for the specified market

## Authentication

If `API_KEY` is set in `.env`, include it in the request header:
```
X-API-Key: your-api-key-here
```

## Development

The project structure:
```
src/
├── main.py                 # FastAPI application
├── config.py               # Configuration management
├── api/                    # API routes and authentication
├── services/               # Business logic services
├── notifications/          # Telegram notifications
├── monitoring/             # Health monitoring
├── utils/                  # Utilities
└── models/                 # Pydantic models
```

## License

MIT

