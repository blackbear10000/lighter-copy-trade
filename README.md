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

