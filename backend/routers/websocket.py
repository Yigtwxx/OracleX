"""
WebSocket Router
Handles real-time price streaming via WebSocket and streaming status.
"""

from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """
    Real-time price streaming via WebSocket.

    Connect to receive live price updates for top cryptocurrencies.
    Updates are pushed as prices change (millisecond latency).

    Message format:
    {
        "type": "price_update",
        "symbol": "BTCUSDT",
        "price": 97000.50,
        "change_24h": 1.25,
        "direction": "up" | "down" | "none",
        "timestamp": "2026-02-09T19:20:00.000000"
    }
    """
    from services.websocket_service import get_connection_manager, get_streaming_service

    manager = get_connection_manager()
    streaming_service = get_streaming_service()

    await websocket.accept()
    await manager.connect(websocket)

    # Start streaming service if not already running
    if not streaming_service.is_running:
        await streaming_service.start()

    try:
        # Send initial snapshot of last known prices
        last_prices = streaming_service.get_last_prices()
        if last_prices:
            await websocket.send_json(
                {"type": "snapshot", "prices": last_prices, "timestamp": datetime.now().isoformat()}
            )

        # Keep connection alive, receive any client messages (ping/pong)
        while True:
            try:
                # Wait for client messages (ping, subscribe, etc.)
                data = await websocket.receive_text()

                # Handle ping/pong for keepalive
                if data == "ping":
                    await websocket.send_text("pong")

            except WebSocketDisconnect:
                break

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)


@router.get("/api/websocket/status")
async def get_websocket_status():
    """Get WebSocket streaming service status."""
    try:
        from services.websocket_service import get_streaming_stats

        stats = await get_streaming_stats()
        return stats
    except Exception as e:
        return {"is_running": False, "error": str(e)}
